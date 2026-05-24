export interface MicrosoftPlatformStatus {
  connected: boolean;
  scopesGranted: string[];
  connectedAt?: string;
  microsoftUserId?: string;
  expiresAt?: string;
}

export interface MicrosoftFeature {
  key: "onedrive" | "mail" | "calendar";
  label: string;
  description: string;
  scope: string;
  envFlag: string;
  icon: string;
  enabled: boolean;
  comingSoon: boolean;
}
