/**
 * Loads the real DSH tool registry, installs the plugin, and asserts that the two
 * tool schemas reach the registry. Then, when WEVISONE_ENDPOINT is reachable, runs
 * one end-to-end prediction through the tool body.
 */
import { Context } from '@deepseek-ai/cordis'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import Tools from '@deepseek-ai/dsh-tools'
import * as plugin from '@wevisone/dsh-wevisone-mcp-plugin'

const EXPECTED = ['wevisone_predict', 'wevisone_doctor']

function fail(message) {
  console.error(`FAIL ${message}`)
  process.exit(1)
}

const endpoint = process.env.WEVISONE_ENDPOINT ?? ''
const token = process.env.WEVISONE_MCP_TOKEN ?? ''

// ToolRuntime declares `inject = ['systemPrompt']`, so the prompt service must
// exist before the tool registry is constructed.
const ctx = new Context()
ctx.plugin(SystemPrompt)
await new Promise((resolve) => setTimeout(resolve, 100))
if (!ctx.get('systemPrompt')) fail('systemPrompt service did not mount')

ctx.plugin(Tools, { mode: 'native' })
await new Promise((resolve) => setTimeout(resolve, 100))
if (!ctx.get('tools')) fail('tools service did not mount')

ctx.plugin(plugin, {
  endpoint: endpoint || undefined,
  token: token || undefined,
  maskDir: process.env.WEVISONE_MASK_DIR ?? '/work/out',
  timeoutMs: Number(process.env.WEVISONE_TIMEOUT_MS ?? 180_000),
})

// cordis starts plugin fibers asynchronously; give the tree a moment to settle.
await new Promise((resolve) => setTimeout(resolve, 250))

const schemas = ctx.tools.schemas()
const names = schemas.map((schema) => schema.name)
console.log(`registered tools (${names.length}): ${names.join(', ') || '<none>'}`)

const missing = EXPECTED.filter((expected) => !names.includes(expected))
if (missing.length > 0) {
  fail(`missing tool(s): ${missing.join(', ')}`)
}

for (const expected of EXPECTED) {
  const schema = schemas.find((entry) => entry.name === expected)
  if (!schema?.description) fail(`${expected} has no description`)
  if (!schema.parameters) fail(`${expected} has no parameter schema`)
}
console.log('OK tool schemas registered')

if (!endpoint) {
  console.log('SKIP end-to-end (no WEVISONE_ENDPOINT set)')
  process.exit(0)
}

const definition = ctx.tools.get('wevisone_doctor')
if (!definition) fail('wevisone_doctor not resolvable from the registry')

const exec = { signal: new AbortController().signal }
const doctorRaw = await definition.execute({}, exec)
const doctor = JSON.parse(doctorRaw)
console.log(`doctor: ok=${doctor.ok} endpoint=${doctor.endpoint} probe=${doctor.probe ?? doctor.error}`)
if (!doctor.ok) fail('endpoint not reachable from this container')

const testImage = process.env.WEVISONE_TEST_IMAGE ?? ''
if (testImage) {
  const predictDefinition = ctx.tools.get('wevisone_predict')
  if (!predictDefinition) fail('wevisone_predict not resolvable from the registry')
  const started = Date.now()
  const raw = await predictDefinition.execute(
    { image_path: testImage, task: 'segmentation', query: 'sofa' },
    exec,
  )
  const result = JSON.parse(raw)
  console.log(`predict: ok=${result.ok} boxes=${JSON.stringify(result.boxes)} rejected=${result.rejected}`)
  if (!result.ok) fail(`prediction failed: ${result.error}`)
  if (result.box_count < 1) fail('expected at least one box for this image')
  const saved = (result.artifacts ?? []).filter((artifact) => artifact.local_path)
  console.log(`mattes saved locally (${saved.length}): ${saved.map((a) => a.local_path).join(', ')}`)
  // 640x640 grayscale PNG starts with these bytes
  for (const artifact of saved) {
    const { readFile } = await import('node:fs/promises')
    const bytes = await readFile(artifact.local_path)
    if (bytes[0] !== 0x89 || bytes[1] !== 0x50) fail(`${artifact.local_path} is not a PNG`)
    console.log(`  ${artifact.local_path}: ${bytes.length} bytes, PNG magic OK`)
  }
  console.log(`OK end-to-end in ${Date.now() - started} ms`)
}

console.log('OK plugin registry + endpoint')
process.exit(0)
