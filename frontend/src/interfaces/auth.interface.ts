export interface User {
  id: string;
  username: string;
  display_name: string;
  role: string;
  is_deleted: boolean;
  create_time: string;
  update_time: string;
  delete_time: string | null;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface AuthResponse {
  status?: string;
  message: string;
  access_token?: string;
  user?: User;
}

export interface AuthError {
  message: string;
  error?: string;
  status?: number;
}

export interface LogoutResponse {
  status: string;
  message: string;
  user_id: string;
}
