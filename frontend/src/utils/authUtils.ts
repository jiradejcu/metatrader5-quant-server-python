/**
 * Authentication-related API utilities
 * Separate from the main apis.ts for better organization
 */

/**
 * Get the authorization header with the current token
 */
export const getAuthHeader = (): { Authorization: string } | {} => {
  const token = localStorage.getItem('access_token');
  if (!token) {
    return {};
  }
  return {
    Authorization: `Bearer ${token}`,
  };
};

/**
 * Check if user has a valid token
 */
export const hasValidToken = (): boolean => {
  return !!localStorage.getItem('access_token');
};

/**
 * Clear authentication data
 */
export const clearAuth = (): void => {
  localStorage.removeItem('access_token');
};

/**
 * Get stored token
 */
export const getToken = (): string | null => {
  return localStorage.getItem('access_token');
};

/**
 * Set token in localStorage
 */
export const setToken = (token: string): void => {
  localStorage.setItem('access_token', token);
};
