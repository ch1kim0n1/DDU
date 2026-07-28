package main

import (
	"net/http"
	"os"
	"strings"
)

const (
	RoleInvestigator = "investigator"
	RoleAnalyst      = "analyst"
	RoleAdmin        = "admin"
	RoleViewer       = "viewer"
	RoleLeadAnalyst  = "lead_analyst"
	RoleOwner        = "investigation_owner"
)

var writeRoles = map[string]bool{
	RoleInvestigator: true,
	RoleAnalyst:      true,
	RoleAdmin:        true,
	RoleLeadAnalyst:  true,
	RoleOwner:        true,
}

func roleFromRequest(r *http.Request) string {
	return identityFromContext(r.Context()).Role
}

func allowLegacyRoleHeader() bool {
	if currentAuthMode() != authModeDev {
		return false
	}
	value := strings.ToLower(strings.TrimSpace(os.Getenv("DDU_ALLOW_ROLE_HEADER")))
	return value == "" || value == "1" || value == "true" || value == "yes"
}

func (s *apiServer) rbacMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" || r.URL.Path == "/versionz" || r.URL.Path == "/" ||
			r.URL.Path == "/v1/auth/dev-token" {
			next.ServeHTTP(w, r)
			return
		}

		id, err := parseBearerToken(r)
		if err != nil {
			if currentAuthMode() == authModeOIDC {
				writeJSON(w, http.StatusUnauthorized, map[string]any{
					"error": "bearer JWT required",
				})
				return
			}
			// AUTH_MODE=dev: optional legacy header for local smoke/tests only.
			if allowLegacyRoleHeader() {
				role := strings.TrimSpace(strings.ToLower(r.Header.Get("X-DDU-Role")))
				if role == "" {
					role = RoleViewer
				}
				id = identityContext{
					UserID: "legacy-header-user",
					Role:   role,
				}
			} else {
				writeJSON(w, http.StatusUnauthorized, map[string]any{
					"error": "bearer JWT required (set AUTH_MODE=dev and DDU_ALLOW_ROLE_HEADER=true for legacy header)",
				})
				return
			}
		}

		r = r.WithContext(withIdentity(r.Context(), id))
		if (r.Method == http.MethodPost || r.Method == http.MethodPatch || r.Method == http.MethodPut) &&
			!writeRoles[id.Role] {
			writeJSON(w, http.StatusForbidden, map[string]any{
				"error":    "insufficient role",
				"required": "investigator, analyst, lead_analyst, investigation_owner, or admin",
				"actual":   id.Role,
			})
			return
		}
		next.ServeHTTP(w, r)
	})
}
