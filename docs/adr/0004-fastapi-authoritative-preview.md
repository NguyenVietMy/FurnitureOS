# FastAPI is authoritative for preview data and placement validation

The approved preview initially used a shared TypeScript placement module and a Next.js backend. That runtime decision is superseded: FastAPI/Pydantic owns the provider-neutral Catalogue, Product normalization checks, convex Room Shells with stable wall IDs, and deterministic metre-based Placement validation. React/Vite fetches a validated Preview Design and only renders the resulting Room Shell, Product, and Placement.

## Considered options

- **Keep the shared TypeScript solver.** It made a browser drag prototype easy, but left two production places that could decide whether furniture fits.
- **Move placement to FastAPI and make the client API-driven.** One authority makes malformed/nonfinite-input rejection, wall contact, access semantics and the +Z invariant testable at the HTTP boundary.

## Consequences

The preview's OpenAPI schema is the contract consumed by the renderer; TypeScript types are generated from it and checked before typechecking. Provider vocabulary is confined to its Catalogue adapter, while the published asset manifest is the sole dimensional and normalization source. FastAPI serves the built Vite SPA safely in local full-app mode; Vercel serves the same static output and routes API requests to the Python entrypoint. A future Nudge must not quietly reuse the old shared-solver assumption: it needs an explicit client-preview experience and a deliberate parity contract with server validation. Supabase remains planned but is not implemented by this slice. This ADR supersedes only the stack/shared-runtime assumption; ADR-0001 through ADR-0003 remain in force.
