import { useMutation, useQuery } from '@tanstack/react-query';
import type { AuthError, AuthResponse, LogoutResponse } from '../interfaces/auth.interface';

/**
 * Hook for user login
 * @param url API base URL
 * @param onSuccess Callback function on successful login with response data
 * @param onError Callback function on login error
 * @returns mutation object with mutate, isPending, error
 */
export const useLogin = (
  url: string,
  onSuccess?: (data: AuthResponse) => void,
  onError?: (error: AuthError) => void
) => {
  return useMutation({
    mutationFn: async (credentials: { username: string; password: string }): Promise<AuthResponse> => {
      const response = await fetch(`${url}/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(credentials),
      });

      const data = await response.json();

      if (!response.ok) {
        throw {
          message: data.message || 'Login failed',
          status: response.status,
        } as AuthError;
      }

      // Store token in localStorage
      if (data.access_token) {
        localStorage.setItem('access_token', data.access_token);
      }

      return data as AuthResponse;
    },
    onSuccess: (data) => {
      onSuccess?.(data);
    },
    onError: (error: AuthError) => {
      onError?.(error);
    },
  });
};

/**
 * Hook for user logout
 * @param url API base URL
 * @param onSuccess Callback function on successful logout with response data
 * @param onError Callback function on logout error
 * @returns mutation object with mutate, isPending, error
 */
export const useLogout = (
  url: string,
  onSuccess?: (data: LogoutResponse) => void,
  onError?: (error: AuthError) => void
) => {
  return useMutation({
    mutationFn: async (): Promise<LogoutResponse> => {
      const token = localStorage.getItem('access_token');
      if (!token) {
        // Token doesn't exist, just clear localStorage
        localStorage.removeItem('access_token');
        return {
          status: 'success',
          message: 'Already logged out',
          user_id: '',
        };
      }

      const response = await fetch(`${url}/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
      });

      const data = await response.json();

      if (!response.ok) {
        throw {
          message: data.message || 'Logout failed',
          status: response.status,
        } as AuthError;
      }

      // Clear token from localStorage
      localStorage.removeItem('access_token');
      
      return data as LogoutResponse;
    },
    onSuccess: (data) => {
      onSuccess?.(data);
    },
    onError: (error: AuthError) => {
      // Always clear token from localStorage even if error occurs
      localStorage.removeItem('access_token');
      onError?.(error);
    },
  });
};

/**
 * Hook to verify if the current token is valid
 * @param url API base URL
 * @returns query object with data, isLoading, error, refetch
 */
export const useVerifyToken = (url: string) => {
  return useQuery({
    queryKey: ['verifyToken'],
    queryFn: async (): Promise<AuthResponse> => {
      const token = localStorage.getItem('access_token');
      if (!token) {
        throw {
          message: 'No token found',
        } as AuthError;
      }

      const response = await fetch(`${url}/verify-token`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
      });

      const data = await response.json();

      if (!response.ok) {
        // Clear invalid token
        localStorage.removeItem('access_token');
        throw {
          message: data.message || 'Token verification failed',
          status: response.status,
        } as AuthError;
      }

      return data as AuthResponse;
    },
    retry: false,
    enabled: !!localStorage.getItem('access_token'),
  });
};
