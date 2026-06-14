import { useState } from "react";
import { login as loginRequest, logout as logoutRequest } from "../query/apis";
import { clearSession, getStoredUser, getToken, setSession } from "../utils/authUtils";
import type { AuthUser, LoginCredentials } from "../interfaces/auth.interface";

export const useAuth = () => {
  const [user, setUser] = useState<AuthUser | null>(getStoredUser());
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isAuthenticated = !!getToken() && !!user;

  const login = async (credentials: LoginCredentials) => {
    setIsLoggingIn(true);
    setError(null);
    try {
      const data = await loginRequest(credentials);
      const authUser: AuthUser = {
        username: data.username,
        is_staff: data.is_staff,
        is_superuser: data.is_superuser,
      };
      setSession(data.token, authUser);
      setUser(authUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      throw err;
    } finally {
      setIsLoggingIn(false);
    }
  };

  const logout = async () => {
    try {
      await logoutRequest();
    } finally {
      clearSession();
      setUser(null);
    }
  };

  return { user, isAuthenticated, isLoggingIn, error, login, logout };
};
