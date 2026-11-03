import { useCallback, useEffect, useState } from "react";
import {
  api,
  ROLES,
  type Handler,
  type Me,
  type TenantSettings,
  type User,
} from "../api";
import { money } from "../format";

function useAction(onDone: () => void) {
  const [error, setError] = useState("");
  const run = useCallback(
    (action: Promise<unknown>) => {
      setError("");
      action.then(onDone, (e: unknown) => {
        setError(e instanceof Error ? e.message : "That did not work.");
      });
    },
    [onDone],
  );
  return { error, run };
}

function UserRow({
  user,
  me,
  act,
}: Readonly<{ user: User; me: Me; act: (action: Promise<unknown>) => void }>) {
  const self = user.user_id === me.user_id;
  function toggle(role: string, on: boolean) {
    const roles = on
      ? [...user.roles, role]
      : user.roles.filter((r) => r !== role);
    act(api.setUserRoles(user.user_id, roles));
  }
  return (
    <tr aria-label={`User ${user.email}`}>
      <td>
        {user.name}
        <div className="muted mono">{user.email}</div>
      </td>
      <td className="mono">{user.handler_id || "—"}</td>
      <td>
        {ROLES.map((role) => (
          <label key={role} className="role">
            <input
              type="checkbox"
              checked={user.roles.includes(role)}
              disabled={self && role === "tenant_admin"}
              onChange={(event) => {
                toggle(role, event.target.checked);
              }}
            />
            {role.replace("_", " ")}
          </label>
        ))}
      </td>
      <td>{user.status}</td>
      <td>
        {!self && (
          <button
            type="button"
            className="button"
            onClick={() => {
              act(
                user.status === "active"
                  ? api.disableUser(user.user_id)
                  : api.enableUser(user.user_id),
              );
            }}
          >
            {user.status === "active" ? "Disable" : "Enable"}
          </button>
        )}
      </td>
    </tr>
  );
}

function NewUserForm({
  handlers,
  act,
}: Readonly<{ handlers: Handler[]; act: (action: Promise<unknown>) => void }>) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<string>("claims_handler");
  const [handlerId, setHandlerId] = useState("");
  return (
    <form
      className="new-user"
      aria-label="Add a sign-in"
      onSubmit={(event) => {
        event.preventDefault();
        act(
          api.createUser({
            name,
            email,
            password,
            roles: [role],
            handler_id: handlerId,
          }),
        );
      }}
    >
      <input
        aria-label="Name"
        placeholder="Name"
        value={name}
        onChange={(event) => {
          setName(event.target.value);
        }}
      />
      <input
        aria-label="New email"
        placeholder="Email"
        value={email}
        onChange={(event) => {
          setEmail(event.target.value);
        }}
      />
      <input
        aria-label="New password"
        type="password"
        placeholder="Password, 12 characters or more"
        value={password}
        onChange={(event) => {
          setPassword(event.target.value);
        }}
      />
      <select
        aria-label="Role"
        value={role}
        onChange={(event) => {
          setRole(event.target.value);
        }}
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r.replace("_", " ")}
          </option>
        ))}
      </select>
      <select
        aria-label="Handler"
        value={handlerId}
        onChange={(event) => {
          setHandlerId(event.target.value);
        }}
      >
        <option value="">Not a handler</option>
        {handlers.map((h) => (
          <option key={h.handler_id} value={h.handler_id}>
            {h.handler_id} {h.name}
          </option>
        ))}
      </select>
      <button type="submit" className="button primary">
        Add
      </button>
    </form>
  );
}

export function Admin({ me }: Readonly<{ me: Me }>) {
  if (!me.roles.includes("tenant_admin")) {
    return (
      <section className="panel" aria-label="Admin">
        <p className="empty">Only a tenant admin can manage sign-ins.</p>
      </section>
    );
  }
  return <AdminPanel me={me} />;
}

function AdminPanel({ me }: Readonly<{ me: Me }>) {
  const [users, setUsers] = useState<User[]>([]);
  const [handlers, setHandlers] = useState<Handler[]>([]);
  const [settings, setSettings] = useState<TenantSettings | null>(null);

  const load = useCallback(() => {
    void api.listUsers().then(setUsers);
    void api.getTenantSettings().then(setSettings);
  }, []);
  const { error, run } = useAction(load);

  useEffect(() => {
    load();
    void api.listHandlers().then(setHandlers);
  }, [load]);

  return (
    <section className="panel" aria-label="Admin">
      <div className="view-head">
        <h2>{settings?.name ?? me.tenant_name}</h2>
        <span className="mono muted">{users.length} sign-ins</span>
      </div>
      {settings && (
        <p className="settings">
          Sign-off over {money(settings.payout_approval_limit)} within{" "}
          {settings.sign_off_sla_hours} hours.{" "}
          <label>
            <input
              type="checkbox"
              checked={settings.external_model_medical}
              onChange={(event) => {
                run(api.setMedical(event.target.checked));
              }}
            />
            Send medical documents to the model
          </label>
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <table className="users">
        <thead>
          <tr>
            <th>Name</th>
            <th>Handler</th>
            <th>Roles</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <UserRow key={user.user_id} user={user} me={me} act={run} />
          ))}
        </tbody>
      </table>
      <NewUserForm handlers={handlers} act={run} />
    </section>
  );
}
