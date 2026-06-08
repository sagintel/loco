const esbuild = require("esbuild");

const args = process.argv.slice(2);
const watch = args.includes("--watch");

async function main() {
  const ctx = await esbuild.context({
    entryPoints: ["src/extension.ts"],
    bundle: true,
    format: "cjs",
    outfile: "dist/extension.js",
    external: ["vscode"],
    platform: "node",
    sourcemap: true,
    minify: false
  });

  if (watch) {
    await ctx.watch();
    console.log("esbuild: watching for changes...");
  } else {
    await ctx.rebuild();
    await ctx.dispose();
    console.log("esbuild: build complete.");
  }
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
