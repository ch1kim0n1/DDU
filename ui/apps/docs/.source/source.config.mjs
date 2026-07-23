// source.config.ts
import { rehypeCodeDefaultOptions } from "fumadocs-core/mdx-plugins";
import { defineConfig, defineDocs } from "fumadocs-mdx/config";
var docs = defineDocs({
  dir: "content/docs"
});
var source_config_default = defineConfig({
  mdxOptions: {
    providerImportSource: "@/mdx-components",
    rehypeCodeOptions: {
      ...rehypeCodeDefaultOptions
      // Preserve meta strings in the output
      // meta: true,
    },
    rehypePlugins: [],
    remarkNpmOptions: {
      persist: {
        id: "package-manager"
      }
    },
    remarkPlugins: []
  }
});
export {
  source_config_default as default,
  docs
};
