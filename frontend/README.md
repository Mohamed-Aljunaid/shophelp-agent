# ShopHelp frontend

React + Vite + TypeScript chat app for the ShopHelp agent API.

```powershell
npm install        # npm cache is on E: (npm_config_cache)
npm run dev        # http://localhost:5280 (needs the API on http://localhost:8000)
npm run build      # type-check and build to dist/
```

Set `VITE_API_URL` to use another API address. The API must allow this origin in `CORS_ORIGINS`.
