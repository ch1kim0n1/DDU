package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
)

type authMode string

const (
	authModeDev  authMode = "dev"
	authModeOIDC authMode = "oidc"
)

type identityContext struct {
	UserID          string
	Role            string
	InvestigationID string
	Email           string
}

type contextKey string

const identityKey contextKey = "ddu-identity"

type jwtClaims struct {
	Role            string `json:"role"`
	InvestigationID string `json:"investigation_id,omitempty"`
	Email           string `json:"email,omitempty"`
	jwt.RegisteredClaims
}

func currentAuthMode() authMode {
	mode := strings.ToLower(strings.TrimSpace(os.Getenv("AUTH_MODE")))
	if mode == string(authModeOIDC) {
		return authModeOIDC
	}
	return authModeDev
}

func jwtSecret() []byte {
	if secret := os.Getenv("DDU_JWT_SECRET"); secret != "" {
		return []byte(secret)
	}
	// Dev-only default; override in every non-local environment.
	return []byte("ddu-dev-jwt-secret-change-me")
}

func identityFromContext(ctx context.Context) identityContext {
	if value, ok := ctx.Value(identityKey).(identityContext); ok {
		return value
	}
	return identityContext{UserID: "anonymous", Role: RoleViewer}
}

func withIdentity(ctx context.Context, id identityContext) context.Context {
	return context.WithValue(ctx, identityKey, id)
}

func parseBearerToken(r *http.Request) (identityContext, error) {
	header := strings.TrimSpace(r.Header.Get("Authorization"))
	if header == "" || !strings.HasPrefix(strings.ToLower(header), "bearer ") {
		return identityContext{}, errors.New("missing bearer token")
	}
	tokenString := strings.TrimSpace(header[7:])
	claims := &jwtClaims{}
	token, err := jwt.ParseWithClaims(tokenString, claims, func(token *jwt.Token) (any, error) {
		if token.Method.Alg() != jwt.SigningMethodHS256.Alg() {
			return nil, errors.New("unexpected signing method")
		}
		return jwtSecret(), nil
	})
	if err != nil || !token.Valid {
		return identityContext{}, errors.New("invalid token")
	}
	role := strings.ToLower(strings.TrimSpace(claims.Role))
	if role == "" {
		role = RoleViewer
	}
	userID := claims.Subject
	if userID == "" {
		userID = "unknown"
	}
	return identityContext{
		UserID:          userID,
		Role:            role,
		InvestigationID: claims.InvestigationID,
		Email:           claims.Email,
	}, nil
}

func mintDevToken(userID, role, investigationID string, ttl time.Duration) (string, error) {
	if userID == "" {
		userID = "dev-user"
	}
	if role == "" {
		role = RoleAnalyst
	}
	now := time.Now().UTC()
	claims := jwtClaims{
		Role:            strings.ToLower(role),
		InvestigationID: investigationID,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
			ID:        uuid.NewString(),
			Issuer:    "ddu-api",
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(jwtSecret())
}

func (s *apiServer) issueDevToken(w http.ResponseWriter, r *http.Request) {
	if currentAuthMode() != authModeDev {
		writeError(w, http.StatusNotFound, "dev token endpoint disabled")
		return
	}
	var input struct {
		UserID          string `json:"user_id"`
		Role            string `json:"role"`
		InvestigationID string `json:"investigation_id"`
		TTLSeconds      int    `json:"ttl_seconds"`
	}
	_ = json.NewDecoder(r.Body).Decode(&input)
	ttl := time.Hour
	if input.TTLSeconds > 0 {
		ttl = time.Duration(input.TTLSeconds) * time.Second
	}
	token, err := mintDevToken(input.UserID, input.Role, input.InvestigationID, ttl)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "token mint failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"access_token": token,
		"token_type":   "Bearer",
		"expires_in":   int(ttl.Seconds()),
		"auth_mode":    string(authModeDev),
	})
}

func (s *apiServer) audit(r *http.Request, action, targetType, targetID string, status int) {
	id := identityFromContext(r.Context())
	entry := map[string]any{
		"timestamp":        time.Now().UTC().Format(time.RFC3339Nano),
		"user_id":          id.UserID,
		"investigation_id": id.InvestigationID,
		"action":           action,
		"target_type":      targetType,
		"target_id":        targetID,
		"result":           status,
		"request_id":       r.Header.Get("X-Request-Id"),
		"ip_address":       r.RemoteAddr,
		"user_agent":       r.UserAgent(),
		"role":             id.Role,
	}
	if entry["request_id"] == "" {
		buf := make([]byte, 8)
		_, _ = rand.Read(buf)
		entry["request_id"] = hex.EncodeToString(buf)
	}
	// Best-effort append to storage audit bucket; never fail the request.
	go s.downstream.appendAudit(entry)
}
