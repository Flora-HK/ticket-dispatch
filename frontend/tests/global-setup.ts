import { apiBaseUrl, backendBaseUrl } from "./config.ts"

export default async function globalSetup() {
  const health = await fetch(`${apiBaseUrl}/health/ready`)
  if (!health.ok) {
    throw new Error(`E2E backend is not ready: HTTP ${health.status}`)
  }

  if (process.env.E2E_SKIP_SEED === "1") return

  process.env.VITE_API_URL = backendBaseUrl
  await import("../scripts/seed-demo.ts")
}
