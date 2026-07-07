// Thin CLI around the Workers-side tokenizer for drift checking.
// stdin:  JSON array of strings
// stdout: JSON array of token arrays (same order)
// Run with: VIEWER_TOKENIZER=/abs/path/to/viewer/functions/lib/tokenizer.ts bun tokenizer-harness.ts
//
// The harness is bundled inside the survey_any package, so it can no longer
// reach the viewer tokenizer by a fixed relative path. The caller passes the
// tokenizer's absolute path via the VIEWER_TOKENIZER env var and we import it
// dynamically.

const mod = await import(process.env.VIEWER_TOKENIZER!);
const Tokenize = mod.Tokenize;

const input = await Bun.stdin.text();
const texts: string[] = JSON.parse(input);
console.log(JSON.stringify(texts.map(Tokenize)));
