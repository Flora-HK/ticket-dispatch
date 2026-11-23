export function expandEnvironmentValue(
  value: string,
  environment: Record<string, string | undefined>,
): string {
  return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g, (_, name: string) => {
    const replacement = environment[name]
    if (replacement === undefined) {
      throw new Error(`Environment variable ${name} is required`)
    }
    return replacement
  })
}

export function toE2EDatabaseUrl(databaseUrl: string): string {
  const parsed = new URL(databaseUrl)
  const databaseName = decodeURIComponent(parsed.pathname.slice(1))
  if (!databaseName || databaseName.includes("/")) {
    throw new Error("Database URL must contain exactly one database name")
  }

  parsed.pathname = `/${databaseName.endsWith("_e2e") ? databaseName : `${databaseName}_e2e`}`
  parsed.hash = ""
  return parsed.toString()
}
