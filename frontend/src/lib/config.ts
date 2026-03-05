export const config = {
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8020",
  authBaseUrl: process.env.NEXT_PUBLIC_AUTH_BASE_URL || "http://localhost:8030",
  pollingIntervalMs: parseInt(process.env.NEXT_PUBLIC_POLLING_INTERVAL || "15000", 10),
  appName: "TG News Analytics",
};
