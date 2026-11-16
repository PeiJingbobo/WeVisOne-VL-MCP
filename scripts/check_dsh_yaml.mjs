#!/usr/bin/env node
/**
 * Validate a DSH overlay file (cordis.patch.yml) before the app has to.
 *
 *   node scripts/check_dsh_yaml.mjs [path]
 *
 * A syntax error here makes DSH fail to start, which is a miserable place to
 * discover a typo. This parses the file with the same YAML library the loader
 * uses, treating `!!js` scalars as plain strings, and renders the MCP
 * Authorization expression so a broken template literal shows up here instead
 * of at boot.
 */
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'

const DEFAULT_PATH = join(homedir(), '.dsh', 'profiles', 'desktop', 'cordis.patch.yml')
const target = process.argv[2] ?? DEFAULT_PATH

function loadYaml() {
  // Prefer the copy the profile already ships; fall back to a global install.
  for (const base of [join(homedir(), '.dsh', 'profiles', 'node_modules', 'yaml')]) {
    try {
      return createRequire(import.meta.url)(base)
    } catch {
      /* try the next candidate */
    }
  }
  throw new Error('cannot find the `yaml` package under ~/.dsh/profiles/node_modules')
}

function collectNamed(node, out = []) {
  if (Array.isArray(node)) {
    for (const item of node) collectNamed(item, out)
  } else if (node && typeof node === 'object') {
    if (typeof node.name === 'string') out.push(node)
    for (const value of Object.values(node)) collectNamed(value, out)
  }
  return out
}

let source
try {
  source = readFileSync(target, 'utf8')
} catch (error) {
  console.error(`FAIL cannot read ${target}: ${error.message}`)
  process.exit(1)
}

const YAML = loadYaml()
let document
try {
  // The scalar keeps its literal text; this only validates the quoting.
  document = YAML.parse(source.replace(/!!js /g, ''))
} catch (error) {
  console.error(`FAIL ${target}`)
  console.error(error.message)
  process.exit(1)
}

const entries = collectNamed(document)
console.log(`OK   ${target}`)
console.log(`     entries with a name: ${entries.length}`)

const mcp = entries.find((entry) => entry.name === '@deepseek-ai/dsh-mcp-client')
if (!mcp) {
  console.log('     no dsh-mcp-client entry (nothing else to check)')
  process.exit(0)
}

const authorization = mcp.config?.headers?.Authorization
if (typeof authorization !== 'string') {
  console.error('FAIL dsh-mcp-client entry has no string Authorization header')
  process.exit(1)
}
try {
  const rendered = new Function(`return ${authorization.replace(/^Bearer /, '')}`)()
  const token = String(rendered).replace(/^Bearer /, '')
  if (!token) {
    console.log('WARN Authorization expression rendered to an empty token')
  } else {
    console.log(`     Authorization renders ok (${token.length} chars)`)
  }
} catch (error) {
  console.error(`FAIL Authorization expression does not evaluate: ${error.message}`)
  process.exit(1)
}
