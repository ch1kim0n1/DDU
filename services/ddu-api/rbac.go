package main

import (
	"net/http"
	"strings"
)

const (
	RoleInvestigator = "investigator"
	RoleAnalyst      = "analyst"
	RoleAdmin        = "admin"
	RoleViewer       = "viewer"
)

var writeRoles = map[string]bool{
	RoleInvestigator: true,
	RoleAnalyst:      true,
	RoleAdmin:        true,
}

func roleFromRequest(r *http.Request) string {
	role := strings.TrimSpace(strings.ToLower(r.Header.Get("X-DDU-Role")))
	if role == "" {
		return RoleViewer
	}
	return role
}

func (s *apiServer) rbacMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		role := roleFromRequest(r)
		if (r.Method == http.MethodPost || r.Method == http.MethodPatch || r.Method == http.MethodPut) &&
			!writeRoles[role] {
			writeJSON(w, http.StatusForbidden, map[string]any{
				"error":    "insufficient role",
				"required": "investigator, analyst, or admin",
				"actual":   role,
			})
			return
		}
		next.ServeHTTP(w, r)
	})
}
