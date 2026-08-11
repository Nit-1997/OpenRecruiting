# Landing / login surface. Next.js standalone output, served by bun.
#
# NEXT_PUBLIC_* are compiled into the browser bundle, so they must be present at
# BUILD time, not just at run time -- hence the build args. They are public by
# definition; never pass a secret this way.
FROM oven/bun:1 AS deps
WORKDIR /app
COPY package.json bun.lock* bun.lockb* ./
# --ignore-scripts: the prepare script installs git hooks, which needs a git
# repo and the git binary -- neither exists (or is wanted) in an image build.
RUN bun install --frozen-lockfile --ignore-scripts

FROM oven/bun:1 AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# No NEXT_PUBLIC_* build args, deliberately. Next.js inlines those into the
# CLIENT BUNDLE at build time, which froze every browser-visible setting into
# the image: a corrected .env then needed a rebuild rather than a restart, and
# nothing said so. They are now read from the environment at REQUEST time by the
# Node server (output: 'standalone') and injected as window.__OR_CONFIG__ by
# src/app/layout.tsx. See src/lib/runtime-config.ts.
#
# Re-adding an ARG here silently restores the bug. src/lib/__tests__/
# no-build-time-config.test.ts guards the source side.
RUN bun run build

FROM oven/bun:1 AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# Run as the image's unprivileged user rather than root.
COPY --from=build --chown=bun:bun /app/.next/standalone ./
COPY --from=build --chown=bun:bun /app/.next/static ./.next/static
COPY --from=build --chown=bun:bun /app/public ./public
USER bun
EXPOSE 3000
CMD ["bun", "server.js"]
