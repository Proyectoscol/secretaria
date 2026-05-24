export interface User {
  id: string;
  tenantId: string;
  email: string;
  fullName: string;
  avatarUrl?: string;
  role: "user" | "admin";
  source: "local" | "microsoft";
  microsoftAuthOid?: string;
  hasPlatformToken: boolean;
  createdAt: string;
  lastLoginAt?: string;
}

export interface Session {
  user: User;
  accessToken: string;
  expires: string;
}

export interface RegisterInput {
  fullName: string;
  email: string;
  password: string;
  confirmPassword: string;
}

export interface LoginInput {
  email: string;
  password: string;
  rememberMe: boolean;
}
