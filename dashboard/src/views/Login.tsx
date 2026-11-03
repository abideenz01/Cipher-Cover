import { useState } from "react";
import { api, type Me } from "../api";

export function Login({
  onSignedIn,
}: Readonly<{ onSignedIn: (me: Me) => void }>) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <main className="login">
      <form
        className="panel login-form"
        aria-label="Sign in"
        onSubmit={(event) => {
          event.preventDefault();
          setError("");
          setBusy(true);
          api.login(email.trim(), password).then(onSignedIn, (e: unknown) => {
            setError(e instanceof Error ? e.message : "Sign-in failed.");
            setBusy(false);
          });
        }}
      >
        <h1>Cipher Cover</h1>
        <label>
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
        </label>
        <label>
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
          />
        </label>
        <button
          type="submit"
          className="button primary"
          disabled={busy || !email.trim() || !password}
        >
          Sign in
        </button>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
