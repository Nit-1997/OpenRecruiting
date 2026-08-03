import http from 'node:http'

const MOCK_USER = {
  id: 'admin-1',
  email: 'admin@example.com',
  aud: 'authenticated',
  role: 'authenticated',
  app_metadata: {},
  user_metadata: { full_name: 'Test Admin' },
  created_at: '2024-01-01T00:00:00Z',
}

const MOCK_SESSION = {
  access_token: 'mock-access-token',
  token_type: 'bearer',
  expires_in: 3600,
  refresh_token: 'mock-refresh-token',
  user: MOCK_USER,
}

const MOCK_PROFILE = {
  id: 'admin-1',
  is_staff: true,
  email: 'admin@example.com',
  full_name: 'Test Admin',
}

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, PATCH, OPTIONS',
  'Access-Control-Allow-Headers': '*',
  'Access-Control-Expose-Headers': '*',
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)

  Object.entries(corsHeaders).forEach(([k, v]) => res.setHeader(k, v))
  res.setHeader('Content-Type', 'application/json')

  if (req.method === 'OPTIONS') {
    res.writeHead(200)
    return res.end()
  }

  if (req.method === 'GET' && url.pathname === '/auth/v1/user') {
    res.writeHead(200)
    return res.end(JSON.stringify(MOCK_USER))
  }

  if (req.method === 'POST' && url.pathname.startsWith('/auth/v1/token')) {
    res.writeHead(200)
    return res.end(JSON.stringify(MOCK_SESSION))
  }

  if (req.method === 'GET' && url.pathname.startsWith('/rest/v1/profiles')) {
    res.writeHead(200)
    return res.end(JSON.stringify(MOCK_PROFILE))
  }

  res.writeHead(200)
  res.end(JSON.stringify({}))
})

server.listen(54321, () => {
  console.log('Mock Supabase server running on http://localhost:54321')
})
