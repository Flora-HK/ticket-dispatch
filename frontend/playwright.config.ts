import { defineConfig, devices } from '@playwright/test';
import path from "node:path"
import dotenv from "dotenv"

import {
  expandEnvironmentValue,
  toE2EDatabaseUrl,
} from "./scripts/e2e-environment.ts"

dotenv.config({ path: path.resolve(import.meta.dirname, "../.env") })

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL
const backendURL = externalBaseURL ?? "http://localhost:8001"
const baseURL = externalBaseURL ?? "http://localhost:5174"
const e2eDatabaseUrl = externalBaseURL
  ? undefined
  : toE2EDatabaseUrl(
      expandEnvironmentValue(
        process.env.E2E_DATABASE_URL ??
          process.env.DATABASE_URL ??
          (() => {
            throw new Error("DATABASE_URL is required to start the E2E backend")
          })(),
        process.env,
      ),
    )

process.env.E2E_BACKEND_URL ??= backendURL
process.env.VITE_API_URL ??= backendURL

const backendPython = path.resolve(
  import.meta.dirname,
  "../.venv/Scripts/python.exe",
)

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './tests',
  globalSetup: './tests/global-setup.ts',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: process.env.CI ? 'blob' : 'html',
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL,

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
  },

  /* Configure projects for major browsers */
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/ },

    {
      name: 'visual-chromium',
      testMatch: /visual\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup'],
    },

    {
      name: 'visual-mobile-chromium',
      testMatch: /visual\.spec\.ts/,
      use: {
        ...devices["Pixel 5"],
        storageState: "playwright/.auth/user.json",
      },
      dependencies: ["setup"],
    },

    {
      name: 'chromium',
      testIgnore: /visual\.spec\.ts/,
      use: {
        ...devices['Desktop Chrome'],
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup', 'visual-chromium', 'visual-mobile-chromium'],
    },

    // {
    //   name: 'firefox',
    //   use: {
    //     ...devices['Desktop Firefox'],
    //     storageState: 'playwright/.auth/user.json',
    //   },
    //   dependencies: ['setup'],
    // },

    // {
    //   name: 'webkit',
    //   use: {
    //     ...devices['Desktop Safari'],
    //     storageState: 'playwright/.auth/user.json',
    //   },
    //   dependencies: ['setup'],
    // },

    /* Test against mobile viewports. */
    {
      name: "mobile-chromium",
      testIgnore: /visual\.spec\.ts/,
      use: {
        ...devices["Pixel 5"],
        storageState: "playwright/.auth/user.json",
      },
      dependencies: ["setup", "visual-chromium", "visual-mobile-chromium"],
    },
    // {
    //   name: 'Mobile Safari',
    //   use: { ...devices['iPhone 12'] },
    // },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],

  /* Run your local dev server before starting the tests */
  webServer: process.env.PLAYWRIGHT_BASE_URL
    ? undefined
    : [
        {
          command:
            `"${backendPython}" scripts/e2e_prepare.py && ` +
            `"${backendPython}" -m uvicorn app.main:app --host 127.0.0.1 --port 8001`,
          cwd: path.resolve(import.meta.dirname, "../backend"),
          env: {
            DATABASE_URL: e2eDatabaseUrl ?? "",
            FRONTEND_HOST: baseURL,
          },
          url: "http://localhost:8001/api/v1/health/live",
          reuseExistingServer: false,
        },
        {
          command: 'bunx vite --host 127.0.0.1 --port 5174',
          env: {
            VITE_API_URL: backendURL,
          },
          url: baseURL,
          reuseExistingServer: false,
        },
      ],
});
