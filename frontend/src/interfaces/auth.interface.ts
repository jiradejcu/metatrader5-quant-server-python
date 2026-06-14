export interface LoginCredentials {
  username: string;
  password: string;
}

export interface AuthUser {
  username: string;
  is_staff: boolean;
  is_superuser: boolean;
}

export interface LoginResponse extends AuthUser {
  token: string;
}
