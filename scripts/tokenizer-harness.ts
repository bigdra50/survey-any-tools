// Thin CLI around the Workers-side tokenizer for drift checking.
// stdin:  JSON array of strings
// stdout: JSON array of token arrays (same order)
// Run with: bun scripts/tokenizer-harness.ts

import { Tokenize } from "../viewer/functions/lib/tokenizer";

const input = await Bun.stdin.text();
const texts: string[] = JSON.parse(input);
console.log(JSON.stringify(texts.map(Tokenize)));
