# Security Policy

Doggy Detector is designed as a local, self-hosted device application. It is not
a hosted multi-user service.

## Supported Use

- Keep the dashboard on a trusted local network or private overlay network such
  as Tailscale.
- Do not expose the dashboard directly to the public internet without an
  authenticated reverse proxy or access-control layer in front of it.
- Keep `data/`, `.env`, local SQLite databases, clips, reports, and generated
  dashboard credentials out of git.
- Treat saved audio clips as private household data.

## Reporting Issues

If you find a security issue, open a private advisory on GitHub if available, or
contact the repository maintainer directly before publishing details.

## Local Recording Notice

This project records local audio when bark incidents are detected. Operators are
responsible for following local recording, privacy, noise, and animal-control
laws.
