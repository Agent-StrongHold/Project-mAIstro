#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { DefaultArtifactClient } = require("@actions/artifact");

function filesUnder(root) {
  const files = [];
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...filesUnder(full));
    } else if (entry.isFile()) {
      files.push(full);
    }
  }
  return files;
}

async function main() {
  const [artifactName, root] = process.argv.slice(2);
  if (!artifactName || !root) {
    throw new Error("usage: upload_mutation_checkpoint.cjs <artifact-name> <directory>");
  }
  const absoluteRoot = path.resolve(root);
  const files = filesUnder(absoluteRoot);
  if (files.length === 0) {
    throw new Error(`checkpoint directory is empty: ${absoluteRoot}`);
  }
  const client = new DefaultArtifactClient();
  const result = await client.uploadArtifact(artifactName, files, absoluteRoot, {
    retentionDays: 7,
    compressionLevel: 6,
  });
  console.log(`uploaded ${artifactName}: artifact id ${result.id}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
