import { useEffect, useState } from "react";
import { api, whenSignedOut, type Me } from "./api";
import { App } from "./App";
import { Login } from "./views/Login";

/** Show the sign-in form until there is a session, then the dashboard. */
export function Session() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    whenSignedOut(() => {
      setMe(null);
    });
    api.me().then(setMe, () => {
      setMe(null);
    });
  }, []);

  if (me === undefined) return <p className="muted">Loading…</p>;
  if (me === null) return <Login onSignedIn={setMe} />;
  return (
    <App
      me={me}
      onSignOut={() => {
        void api.logout().finally(() => {
          setMe(null);
        });
      }}
    />
  );
}
