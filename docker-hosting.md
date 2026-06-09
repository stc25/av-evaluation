# Hosting Multiple Docker Containers on One Domain with Caddy

This guide shows how to serve multiple Docker containers from one domain using Caddy as a reverse proxy with automatic HTTPS.

Target URLs:

```text
https://cnlp.langcen.cam.ac.uk/av-evaluation
https://cnlp.langcen.cam.ac.uk/german-chat
```

Caddy listens on ports `80` and `443`, obtains and renews TLS certificates automatically, and forwards requests to the correct container based on the URL path.

## Architecture

```text
Internet
   |
   v
cnlp.langcen.cam.ac.uk
   |
   v
Caddy container, ports 80 and 443
   |
   +-- /av-evaluation/*  -> av-evaluation container
   |
   +-- /german-chat/*    -> german-chat container
```

Only the Caddy container needs to publish ports to the host. The application containers can stay private on the Docker network.

## Prerequisites

Before starting, make sure:

- `cnlp.langcen.cam.ac.uk` has a DNS `A` or `CNAME` record pointing to the server.
- Ports `80` and `443` are open on the server firewall.
- No other service is already using ports `80` or `443`.
- Docker and Docker Compose are installed.
- The application containers listen on known internal ports, such as `8000`.

## Example File Layout

```text
hosting/
  docker-compose.yml
  Caddyfile
```

## Docker Compose

Create `docker-compose.yml`:

```yaml
services:
  caddy:
    image: caddy:latest
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - av-evaluation
      - german-chat

  av-evaluation:
    image: your-av-evaluation-image
    restart: unless-stopped
    expose:
      - "8000"

  german-chat:
    image: your-german-chat-image
    restart: unless-stopped
    expose:
      - "8000"

volumes:
  caddy_data:
  caddy_config:
```

Replace `your-av-evaluation-image` and `your-german-chat-image` with the actual image names.

If you build the images locally from directories instead, use `build`:

```yaml
  av-evaluation:
    build: ./av-evaluation
    restart: unless-stopped
    expose:
      - "8000"

  german-chat:
    build: ./german-chat
    restart: unless-stopped
    expose:
      - "8000"
```

## Caddyfile

Create `Caddyfile`:

```caddyfile
cnlp.langcen.cam.ac.uk {
    handle_path /av-evaluation/* {
        reverse_proxy av-evaluation:8000
    }

    handle_path /german-chat/* {
        reverse_proxy german-chat:8000
    }
}
```

`handle_path` strips the matching prefix before forwarding the request.

For example:

```text
https://cnlp.langcen.cam.ac.uk/av-evaluation/results
```

is forwarded to the `av-evaluation` container as:

```text
/results
```

This is usually the right choice when each application expects to run from `/`.

## When Not to Strip the Path Prefix

If an application is configured to know that it is hosted under `/av-evaluation` or `/german-chat`, use `handle` instead of `handle_path`:

```caddyfile
cnlp.langcen.cam.ac.uk {
    handle /av-evaluation/* {
        reverse_proxy av-evaluation:8000
    }

    handle /german-chat/* {
        reverse_proxy german-chat:8000
    }
}
```

With `handle`, the full path is preserved.

For example:

```text
/av-evaluation/results
```

is forwarded to the container unchanged as:

```text
/av-evaluation/results
```

## Redirect Bare Paths

Users may visit `/av-evaluation` without the trailing slash. Add redirects so both forms work:

```caddyfile
cnlp.langcen.cam.ac.uk {
    redir /av-evaluation /av-evaluation/
    redir /german-chat /german-chat/

    handle_path /av-evaluation/* {
        reverse_proxy av-evaluation:8000
    }

    handle_path /german-chat/* {
        reverse_proxy german-chat:8000
    }
}
```

## Recommended Starting Caddyfile

Use this version first:

```caddyfile
cnlp.langcen.cam.ac.uk {
    redir /av-evaluation /av-evaluation/
    redir /german-chat /german-chat/

    handle_path /av-evaluation/* {
        reverse_proxy av-evaluation:8000
    }

    handle_path /german-chat/* {
        reverse_proxy german-chat:8000
    }
}
```

## Start the Stack

From the directory containing `docker-compose.yml` and `Caddyfile`, run:

```bash
docker compose up -d
```

Check that the containers are running:

```bash
docker compose ps
```

Check Caddy logs:

```bash
docker compose logs -f caddy
```

Caddy should automatically request a certificate for `cnlp.langcen.cam.ac.uk`.

## Test the Routes

Test in a browser:

```text
https://cnlp.langcen.cam.ac.uk/av-evaluation/
https://cnlp.langcen.cam.ac.uk/german-chat/
```

Or with `curl`:

```bash
curl -I https://cnlp.langcen.cam.ac.uk/av-evaluation/
curl -I https://cnlp.langcen.cam.ac.uk/german-chat/
```

## Updating an Application

To update one application image:

```bash
docker compose pull av-evaluation
docker compose up -d av-evaluation
```

For locally built images:

```bash
docker compose build av-evaluation
docker compose up -d av-evaluation
```

Caddy does not usually need to restart when only the application container changes.

## Adding Another Container

To add another app, add a new service to `docker-compose.yml`:

```yaml
  new-app:
    image: your-new-app-image
    restart: unless-stopped
    expose:
      - "8000"
```

Then add a route to `Caddyfile`:

```caddyfile
    redir /new-app /new-app/

    handle_path /new-app/* {
        reverse_proxy new-app:8000
    }
```

Reload Caddy:

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Then start the new service:

```bash
docker compose up -d new-app
```

## Common Issues

### Caddy cannot get a certificate

Check:

- DNS points to the correct server.
- Ports `80` and `443` are reachable from the internet.
- The server firewall allows inbound HTTP and HTTPS.
- No other process is using ports `80` or `443`.

### App works locally but not under the path

The app may be generating links to `/assets`, `/static`, `/login`, or API routes at the domain root.

Options:

- Configure the app with a base path such as `/av-evaluation`.
- Use `handle` instead of `handle_path`.
- Prefer subdomains if the app cannot run correctly under a path prefix.

### Static assets return 404

This usually means the app is not path-prefix aware. For example, the page is under `/av-evaluation/`, but the browser requests `/static/app.js` instead of `/av-evaluation/static/app.js`.

Fix this in the app's base URL, asset prefix, or root path settings.

### WebSockets do not work

Caddy supports WebSockets automatically through `reverse_proxy`. If WebSockets fail, check the application container port, route path, and app-side origin settings.

## Path Routing vs Subdomains

Path routing:

```text
https://cnlp.langcen.cam.ac.uk/av-evaluation/
https://cnlp.langcen.cam.ac.uk/german-chat/
```

Advantages:

- Only one domain is needed.
- One Caddy site block handles all apps.

Disadvantages:

- Apps must work correctly under a path prefix, or the proxy must strip the prefix.

Subdomains:

```text
https://av-evaluation.cnlp.langcen.cam.ac.uk/
https://german-chat.cnlp.langcen.cam.ac.uk/
```

Advantages:

- Usually easier for web apps.
- Each app can behave as if it is hosted at `/`.

Disadvantages:

- Requires DNS records for each subdomain.

For the requested setup, path routing with Caddy is fine, but subdomains are often simpler if either app has trouble with asset paths, login callbacks, cookies, or API routes.

## Operational Workflow

1. Create or update the application container.
2. Confirm which port the app listens on inside Docker.
3. Add the service to `docker-compose.yml`.
4. Add a matching `handle_path` route to `Caddyfile`.
5. Run `docker compose up -d`.
6. Watch Caddy logs with `docker compose logs -f caddy`.
7. Test the public HTTPS URL.
8. If assets, redirects, or login flows break, check whether the app needs a base path setting or whether the Caddy route should use `handle` instead of `handle_path`.

## Minimal Production Checklist

- Use `restart: unless-stopped` for all services.
- Persist Caddy data with the `caddy_data` volume.
- Keep only Caddy exposed to the public internet.
- Do not publish app ports with `ports` unless there is a specific reason.
- Use `expose` for app ports so they are available only inside the Docker network.
- Keep the `Caddyfile` in version control.
- Check logs after every deployment.
