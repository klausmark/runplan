# Changelog

Notable changes for users and integrators are documented in this file.

The project follows Semantic Versioning. During initial development, intentional breaking
changes may be released in a new minor version.

## Unreleased

- Added YAML-based workout creation from empty calendar days, including a valid
  starter template and an in-dialog syntax reference.
- Added confirmed workout deletion while deferring cleanup of synchronized
  Garmin objects to the next reviewed sync.
- Added one shared password gate for Runplan Studio with persistent browser
  authorization, HTTPS-aware cookies, challenge-response login, and basic
  in-memory rate limiting.
- Added `runplan hash-password` and Docker environment configuration for the
  recommended salted password verifier.
