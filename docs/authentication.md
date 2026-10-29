# TrustLens AI authentication

- Google OAuth is the only sign-in method currently offered by the frontend.
- The frontend authenticates through Supabase Auth using the existing Google OAuth provider.
- Email OTP is not offered by the UI. Supabase's Email provider and email settings have not been disabled or changed by this application change.
- Signed-in sessions are restored and observed through the shared Supabase client. Successful Google sign-in routes users to the analyzer; signing out returns them to the sign-in page.
- Email authentication can be reintroduced later if the product requires it.

Google OAuth credentials, provider settings, callback URLs, and environment variable names are configured outside the frontend code and were not changed here.
