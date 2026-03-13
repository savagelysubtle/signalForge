# Cross-Platform AppData Storage Pattern for SQLite Databases

> **Purpose**: This document describes how to store per-user SQLite databases in the OS-standard application data directory (e.g. `%APPDATA%` on Windows). Copy this pattern into any Node.js, Electron, or TypeScript project.

---

## The Core Idea

Every OS has a standard directory for persisting per-user application data:

| OS      | Path                                                        | Env Variable      |
|---------|-------------------------------------------------------------|--------------------|
| Windows | `C:\Users\<USER>\AppData\Roaming\<AppName>\`               | `%APPDATA%`        |
| macOS   | `~/Library/Application Support/<AppName>/`                  | —                  |
| Linux   | `~/.config/<AppName>/`                                      | `$XDG_CONFIG_HOME` |

You resolve this path at runtime, create your subdirectory structure under it, and point your SQLite databases there.

---

## Step 1: Resolve the AppData Path

```typescript
// appDataPath.ts
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';

/**
 * Returns the OS-standard application data directory for the given app name.
 *
 * Windows: %APPDATA%\<appName>        (e.g. C:\Users\Steve\AppData\Roaming\MyApp)
 * macOS:   ~/Library/Application Support/<appName>
 * Linux:   $XDG_CONFIG_HOME/<appName> (defaults to ~/.config/<appName>)
 */
export function getAppDataPath(appName: string): string {
  let appDataDir: string;

  switch (process.platform) {
    case 'win32':
      appDataDir = process.env['APPDATA']
        || path.join(process.env['USERPROFILE'] || os.homedir(), 'AppData', 'Roaming');
      break;
    case 'darwin':
      appDataDir = path.join(os.homedir(), 'Library', 'Application Support');
      break;
    case 'linux':
      appDataDir = process.env['XDG_CONFIG_HOME'] || path.join(os.homedir(), '.config');
      break;
    default:
      throw new Error(`Unsupported platform: ${process.platform}`);
  }

  return path.join(appDataDir, appName);
}

/**
 * Ensures a directory exists, creating it recursively if needed.
 */
export function ensureDir(dirPath: string): void {
  fs.mkdirSync(dirPath, { recursive: true });
}
```

---

## Step 2: Define Your Database Path Service

```typescript
// databasePaths.ts
import * as path from 'path';
import { getAppDataPath, ensureDir } from './appDataPath';

const APP_NAME = 'YourAppName'; // <-- CHANGE THIS to your app's name

export class DatabasePathService {
  private baseDir: string;

  constructor() {
    this.baseDir = getAppDataPath(APP_NAME);
  }

  /** Root storage directory for all app data */
  getBaseDir(): string {
    return this.baseDir;
  }

  /** Directory for all workspace-scoped databases */
  getWorkspacesDir(): string {
    return path.join(this.baseDir, 'databases', 'workspaces');
  }

  /** Per-workspace database paths (isolated by workspace ID) */
  getWorkspaceDir(workspaceId: string): string {
    return path.join(this.getWorkspacesDir(), workspaceId);
  }

  getThreadsDbPath(workspaceId: string): string {
    return path.join(this.getWorkspaceDir(workspaceId), 'threads.db');
  }

  getEmailsDbPath(workspaceId: string): string {
    return path.join(this.getWorkspaceDir(workspaceId), 'emails.db');
  }

  getMainDbPath(workspaceId: string): string {
    return path.join(this.getWorkspaceDir(workspaceId), 'main.db');
  }

  /** Shared paths (not per-workspace) */
  getLogsDir(): string {
    return path.join(this.baseDir, 'logs');
  }

  getModelCacheDir(): string {
    return path.join(this.baseDir, 'models');
  }

  /** Call once at startup to create the directory tree */
  ensureDirectories(workspaceId?: string): void {
    ensureDir(this.baseDir);
    ensureDir(this.getWorkspacesDir());
    ensureDir(this.getLogsDir());
    ensureDir(this.getModelCacheDir());

    if (workspaceId) {
      ensureDir(this.getWorkspaceDir(workspaceId));
    }
  }
}
```

---

## Step 3: Use It

```typescript
import { DatabasePathService } from './databasePaths';
import Database from 'better-sqlite3'; // or any SQLite library

const paths = new DatabasePathService();
const workspaceId = 'my-project-abc123';

// Create directories on startup
paths.ensureDirectories(workspaceId);

// Open databases
const threadsDb = new Database(paths.getThreadsDbPath(workspaceId));
const emailsDb  = new Database(paths.getEmailsDbPath(workspaceId));

// Resulting file locations (Windows example):
// C:\Users\Steve\AppData\Roaming\YourAppName\databases\workspaces\my-project-abc123\threads.db
// C:\Users\Steve\AppData\Roaming\YourAppName\databases\workspaces\my-project-abc123\emails.db
```

---

## Step 4 (Optional): Workspace ID Hashing

If your workspace IDs come from file paths (like a project directory), hash them to short safe strings:

```typescript
import * as crypto from 'crypto';

export function hashWorkspaceId(workspacePath: string): string {
  return crypto.createHash('sha256').update(workspacePath).digest('hex').substring(0, 8);
}

// Usage:
const workspaceId = hashWorkspaceId('D:\\Projects\\MyProject');
// Result: "2fb73011" (8-char hex)
```

---

## Directory Structure Result

```
%APPDATA%\YourAppName\              (or ~/Library/Application Support/... on macOS)
├── databases\
│   └── workspaces\
│       ├── <workspace-id-1>\
│       │   ├── threads.db
│       │   ├── emails.db
│       │   └── main.db
│       └── <workspace-id-2>\
│           ├── threads.db
│           ├── emails.db
│           └── main.db
├── logs\
└── models\
```

---

## Key Design Decisions

1. **Per-workspace isolation**: Each workspace/project gets its own database directory. No global database mixes data across projects.
2. **`fs.mkdirSync({ recursive: true })`**: Safe to call multiple times; no-ops if directory exists.
3. **Platform fallbacks**: On Windows, falls back to `%USERPROFILE%\AppData\Roaming` if `%APPDATA%` is missing.
4. **No hardcoded paths**: Everything derived from OS environment variables at runtime.
5. **Separate concerns**: Logs and model caches are siblings to `databases/`, not inside it.

---

## Origin

This pattern is extracted from the SafeAppeals2.0 codebase (a VSCode/Electron fork). The original implementation uses VSCode's `IEnvironmentService.userRoamingDataHome` which resolves identically to `getAppDataPath()` above — it just wraps it in VSCode's service/DI system. The standalone version above has no VSCode dependencies.
