# Staff admin portal. Next.js standalone output, served by bun.
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
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_API_V2_URL
ARG NEXT_PUBLIC_ASSESSMENT_UI_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY \
    NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_API_V2_URL=$NEXT_PUBLIC_API_V2_URL \
    NEXT_PUBLIC_ASSESSMENT_UI_URL=$NEXT_PUBLIC_ASSESSMENT_UI_URL
RUN bun run build

FROM oven/bun:1 AS run
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
# Run as the image's unprivileged user rather than root.
COPY --from=build --chown=bun:bun /app/.next/standalone ./
COPY --from=build --chown=bun:bun /app/.next/static ./.next/static
COPY --from=build --chown=bun:bun /app/public ./public
USER bun
EXPOSE 3000
CMD ["bun", "server.js"]
