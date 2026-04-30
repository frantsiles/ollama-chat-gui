/**
 * FileTypeRegistry — resolves a filename to a viewer configuration.
 *
 * Priority order:
 *   1. Exact filename match (case-insensitive) — handles Dockerfile, web.config, .gitignore, etc.
 *   2. Extension match (lowercase, without leading dot)
 *   3. Fallback: plain text
 *
 * To add support for a new file type call:
 *   FileTypeRegistry.register('ext', config)           // by extension
 *   FileTypeRegistry.register('filename', config, 'name') // by exact name
 *
 * ViewerConfig shape:
 *   { type: 'code'|'markdown'|'json'|'xml'|'text', lang: string|null, label: string, canPreview: boolean }
 */
const FileTypeRegistry = (() => {
    const CODE = (lang, label) => ({ type: 'code', lang, label, canPreview: false });
    const MD   = { type: 'markdown', lang: 'markdown', label: 'Markdown', canPreview: true };
    const JSON_V = { type: 'json',  lang: 'json',  label: 'JSON', canPreview: false };
    const XML_V  = { type: 'xml',   lang: 'xml',   label: 'XML',  canPreview: false };
    const TEXT   = { type: 'text',  lang: null,    label: 'Texto', canPreview: false };

    // --- Exact filename entries (full name, including dots, case-insensitive) ---
    const byName = {
        'dockerfile':         CODE('dockerfile', 'Dockerfile'),
        'makefile':           CODE('makefile',   'Makefile'),
        'rakefile':           CODE('ruby',       'Rakefile'),
        'gemfile':            CODE('ruby',       'Gemfile'),
        'podfile':            CODE('ruby',       'Podfile'),
        'vagrantfile':        CODE('ruby',       'Vagrantfile'),
        'jenkinsfile':        CODE('groovy',     'Jenkinsfile'),
        'brewfile':           CODE('ruby',       'Brewfile'),
        'procfile':           TEXT,
        '.gitignore':         CODE('gitignore',  '.gitignore'),
        '.gitattributes':     TEXT,
        '.gitmodules':        CODE('ini',        '.gitmodules'),
        '.editorconfig':      CODE('ini',        '.editorconfig'),
        '.prettierrc':        JSON_V,
        '.eslintrc':          JSON_V,
        '.babelrc':           JSON_V,
        '.nvmrc':             TEXT,
        '.env':               CODE('bash',       '.env'),
        '.env.local':         CODE('bash',       '.env'),
        '.env.example':       CODE('bash',       '.env'),
        '.npmrc':             CODE('ini',        '.npmrc'),
        'web.config':         XML_V,
        'app.config':         XML_V,
        'appsettings.json':   JSON_V,
        'cargo.toml':         CODE('toml',       'Cargo.toml'),
        'cargo.lock':         CODE('toml',       'Cargo.lock'),
        'go.mod':             CODE('go',         'go.mod'),
        'go.sum':             TEXT,
        'cmakelists.txt':     CODE('cmake',      'CMakeLists.txt'),
        'requirements.txt':   TEXT,
        'pipfile':            CODE('toml',       'Pipfile'),
        'pyproject.toml':     CODE('toml',       'pyproject.toml'),
        'package.json':       JSON_V,
        'package-lock.json':  JSON_V,
        'yarn.lock':          TEXT,
        'pnpm-lock.yaml':     CODE('yaml',       'pnpm-lock.yaml'),
        '.htaccess':          CODE('apacheconf',  '.htaccess'),
        'nginx.conf':         CODE('nginx',       'nginx.conf'),
        'apache.conf':        CODE('apacheconf',  'apache.conf'),
    };

    // --- Extension entries (lowercase, no leading dot) ---
    const byExt = {
        // Python
        py: CODE('python', 'Python'), pyw: CODE('python', 'Python'),
        // JavaScript
        js: CODE('javascript', 'JavaScript'), mjs: CODE('javascript', 'JavaScript'),
        cjs: CODE('javascript', 'JavaScript'),
        // TypeScript
        ts: CODE('typescript', 'TypeScript'), tsx: CODE('typescript', 'TypeScript/React'),
        // React JSX
        jsx: CODE('javascript', 'React/JSX'),
        // Rust
        rs: CODE('rust', 'Rust'),
        // Go
        go: CODE('go', 'Go'),
        // Java / JVM
        java: CODE('java', 'Java'), kt: CODE('kotlin', 'Kotlin'), kts: CODE('kotlin', 'Kotlin'),
        scala: CODE('scala', 'Scala'), clj: CODE('clojure', 'Clojure'),
        // C-family
        c: CODE('c', 'C'), h: CODE('c', 'C Header'),
        cpp: CODE('cpp', 'C++'), cc: CODE('cpp', 'C++'), cxx: CODE('cpp', 'C++'),
        hpp: CODE('cpp', 'C++ Header'),
        // .NET
        cs: CODE('csharp', 'C#'), vb: CODE('vbnet', 'VB.NET'),
        fs: CODE('fsharp', 'F#'), fsx: CODE('fsharp', 'F#'),
        // Other languages
        swift: CODE('swift', 'Swift'), rb: CODE('ruby', 'Ruby'),
        php: CODE('php', 'PHP'), lua: CODE('lua', 'Lua'),
        r: CODE('r', 'R'), ex: CODE('elixir', 'Elixir'), exs: CODE('elixir', 'Elixir'),
        erl: CODE('erlang', 'Erlang'), hrl: CODE('erlang', 'Erlang'),
        ml: CODE('ocaml', 'OCaml'), mli: CODE('ocaml', 'OCaml'),
        hs: CODE('haskell', 'Haskell'), lhs: CODE('haskell', 'Haskell'),
        elm: CODE('elm', 'Elm'), dart: CODE('dart', 'Dart'),
        nim: CODE('nim', 'Nim'), zig: CODE('zig', 'Zig'),
        // Web
        html: CODE('html', 'HTML'), htm: CODE('html', 'HTML'),
        css: CODE('css', 'CSS'), scss: CODE('scss', 'SCSS'),
        sass: CODE('sass', 'Sass'), less: CODE('less', 'Less'),
        svelte: CODE('svelte', 'Svelte'), vue: CODE('vue', 'Vue'),
        // Data / config
        json: JSON_V, json5: JSON_V, jsonc: JSON_V,
        yaml: CODE('yaml', 'YAML'), yml: CODE('yaml', 'YAML'),
        toml: CODE('toml', 'TOML'), ini: CODE('ini', 'INI'),
        cfg: CODE('ini', 'Config'), conf: CODE('ini', 'Config'),
        xml: XML_V, xsd: XML_V, xsl: XML_V, xslt: XML_V,
        config: XML_V,
        properties: CODE('properties', 'Properties'),
        env: CODE('bash', 'Env'), plist: XML_V,
        // DB / query
        sql: CODE('sql', 'SQL'), psql: CODE('pgsql', 'PostgreSQL'),
        graphql: CODE('graphql', 'GraphQL'), gql: CODE('graphql', 'GraphQL'),
        // Shell / scripts
        sh: CODE('bash', 'Shell'), bash: CODE('bash', 'Bash'),
        zsh: CODE('bash', 'Zsh'), fish: CODE('fish', 'Fish'),
        ps1: CODE('powershell', 'PowerShell'), bat: CODE('batch', 'Batch'),
        cmd: CODE('batch', 'Batch'),
        // Docs
        md: MD, mdx: MD,
        rst: CODE('plaintext', 'reStructuredText'),
        txt: TEXT, log: TEXT, tex: CODE('latex', 'LaTeX'),
        // Build / infra
        tf: CODE('hcl', 'Terraform'), hcl: CODE('hcl', 'HCL'),
        cmake: CODE('cmake', 'CMake'), mk: CODE('makefile', 'Makefile'),
        gradle: CODE('groovy', 'Gradle'),
        // Other text
        proto: CODE('protobuf', 'Protobuf'), thrift: CODE('thrift', 'Thrift'),
        diff: CODE('diff', 'Diff'), patch: CODE('diff', 'Patch'),
        csv: TEXT, tsv: TEXT, lock: TEXT,
    };

    return {
        /**
         * Resolve a viewer config from a filename.
         * @param {string} filename  The filename (basename, not full path).
         * @returns {ViewerConfig}
         */
        resolve(filename) {
            const lower = filename.toLowerCase();
            // 1. Exact name (handles Dockerfile, web.config, .gitignore, etc.)
            if (byName[lower]) return byName[lower];
            // 2. Extension
            const dot = lower.lastIndexOf('.');
            if (dot !== -1) {
                const ext = lower.slice(dot + 1);
                if (byExt[ext]) return byExt[ext];
            }
            // 3. Fallback
            return TEXT;
        },

        /**
         * Register a new viewer config at runtime.
         * @param {string} key          Extension or exact filename.
         * @param {object} config       ViewerConfig object.
         * @param {'ext'|'name'} by     Lookup table to add to.
         */
        register(key, config, by = 'ext') {
            if (by === 'name') byName[key.toLowerCase()] = config;
            else byExt[key.toLowerCase()] = config;
        },

        /** Convenience factories exposed for external callers. */
        types: { CODE, MD, JSON_V, XML_V, TEXT },
    };
})();

window.FileTypeRegistry = FileTypeRegistry;
