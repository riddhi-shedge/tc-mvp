import { FormEvent, useEffect, useState } from "react";
import { orgApi, OrgMe, ApiError } from "../lib/api";
import { supabase } from "../lib/supabase";
import { Icon } from "../lib/icons";
import { toast } from "../lib/ui";

/** Workspace settings (Track A5/A6): who's in this workspace, teammate invite
 *  links, the inbound email address, and where approved messages may be sent.
 *  Owners manage; members see the roster and the inbound address. */

export function OrgSettings() {
  const [me, setMe] = useState<OrgMe | null>(null);
  const [myId, setMyId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Invite form
  const [invEmail, setInvEmail] = useState("");
  const [invRole, setInvRole] = useState("member");
  const [invBusy, setInvBusy] = useState(false);
  // The one-time join link for the invite just created.
  const [freshLink, setFreshLink] = useState<{ email: string; url: string } | null>(null);

  // Send settings form (local draft; Save persists)
  const [mode, setMode] = useState<"allowlist" | "open">("allowlist");
  const [list, setList] = useState<string[]>([]);
  const [newAddr, setNewAddr] = useState("");
  const [saveBusy, setSaveBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  async function reload() {
    try {
      const data = await orgApi.me();
      setMe(data);
      if (data.settings) {
        setMode(data.settings.send_mode);
        setList(data.settings.send_allowlist);
      }
      setDirty(false);
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load workspace");
    }
  }

  // Account (self): display name lives in Supabase user_metadata and rides the
  // JWT into drafted-message signatures; email changes confirm via Supabase.
  const [displayName, setDisplayName] = useState("");
  const [myEmail, setMyEmail] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [acctBusy, setAcctBusy] = useState(false);

  useEffect(() => {
    void reload();
    void supabase.auth.getUser().then(({ data }) => {
      setMyId(data.user?.id ?? null);
      setMyEmail(data.user?.email ?? "");
      const name = (data.user?.user_metadata as { display_name?: string } | null)?.display_name;
      if (typeof name === "string") setDisplayName(name);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function saveDisplayName(e: FormEvent) {
    e.preventDefault();
    setAcctBusy(true);
    try {
      const { error } = await supabase.auth.updateUser({
        data: { display_name: displayName.trim() },
      });
      if (error) throw error;
      toast("Name saved. It appears in drafted messages after your next sign-in.");
    } catch {
      toast("Could not save your name");
    } finally {
      setAcctBusy(false);
    }
  }

  async function changeEmail(e: FormEvent) {
    e.preventDefault();
    const addr = newEmail.trim();
    if (!addr) return;
    setAcctBusy(true);
    try {
      const { error } = await supabase.auth.updateUser({ email: addr });
      if (error) throw error;
      setNewEmail("");
      toast(`Confirmation sent to ${addr} — the change applies once you confirm.`);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not start the email change");
    } finally {
      setAcctBusy(false);
    }
  }

  async function resetMfa(userId: string, memberEmail: string | null) {
    if (
      !window.confirm(
        `Reset the authenticator for ${memberEmail ?? "this member"}? ` +
          "They'll set up a new one at their next sign-in.",
      )
    )
      return;
    try {
      await orgApi.resetMemberMfa(userId);
      toast("Authenticator reset. Their next sign-in sets up a new one.");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not reset the authenticator");
    }
  }

  function copy(text: string, label: string) {
    void navigator.clipboard?.writeText(text).then(() => toast(`${label} copied`));
  }

  async function createInvite(e: FormEvent) {
    e.preventDefault();
    setInvBusy(true);
    try {
      const inv = await orgApi.invite(invEmail.trim(), invRole);
      const url = `${window.location.origin}/#join=${inv.token}`;
      setFreshLink({ email: inv.email, url });
      setInvEmail("");
      await reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not create the invite");
    } finally {
      setInvBusy(false);
    }
  }

  async function revoke(id: string) {
    try {
      await orgApi.revokeInvite(id);
      toast("Invite revoked");
      setFreshLink(null);
      await reload();
    } catch {
      toast("Could not revoke the invite");
    }
  }

  async function removeMember(userId: string, memberEmail: string | null) {
    if (!window.confirm(`Remove ${memberEmail ?? "this member"} from the workspace?`)) return;
    try {
      await orgApi.removeMember(userId);
      toast("Member removed");
      await reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not remove the member");
    }
  }

  function addAddress(e: FormEvent) {
    e.preventDefault();
    const addr = newAddr.trim().toLowerCase();
    if (!addr) return;
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(addr)) {
      toast("That doesn't look like an email address");
      return;
    }
    if (!list.includes(addr)) {
      setList((l) => [...l, addr]);
      setDirty(true);
    }
    setNewAddr("");
  }

  async function saveSettings() {
    setSaveBusy(true);
    try {
      await orgApi.updateSettings({ send_mode: mode, send_allowlist: list });
      toast("Sending settings saved");
      await reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not save settings");
    } finally {
      setSaveBusy(false);
    }
  }

  if (loadError) return <p className="error">{loadError}</p>;
  if (!me) return <p className="muted">Loading workspace…</p>;
  const isOwner = me.role === "owner";

  return (
    <div className="org">
      <div className="org-head">
        <h2>{me.name}</h2>
        <span className="badge">{isOwner ? "Owner" : "Member"}</span>
      </div>

      {me.inbound_address && (
        <div className="card org-card">
          <h3><Icon name="mail" size={15} /> Inbound email</h3>
          <p className="muted">
            Forward or BCC deal documents to this address and they land in your inbox queue.
          </p>
          <div className="org-mono">
            <code>{me.inbound_address}</code>
            <button className="kbtn" onClick={() => copy(me.inbound_address!, "Address")}>
              Copy
            </button>
          </div>
        </div>
      )}

      <div className="card org-card">
        <h3><Icon name="users" size={15} /> Members</h3>
        <table className="org-table">
          <tbody>
            {me.members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email ?? m.user_id}</td>
                <td><span className="badge">{m.role}</span></td>
                <td className="org-row-act">
                  {isOwner && m.user_id !== myId && (
                    <>
                      <button className="kbtn" onClick={() => void resetMfa(m.user_id, m.email)}>
                        Reset MFA
                      </button>{" "}
                      <button className="kbtn" onClick={() => void removeMember(m.user_id, m.email)}>
                        Remove
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {isOwner && (
          <>
            <h4>Invite a teammate</h4>
            <form className="org-invite-form" onSubmit={createInvite}>
              <input
                type="email"
                placeholder="teammate@company.com"
                value={invEmail}
                onChange={(e) => setInvEmail(e.target.value)}
                required
              />
              <select value={invRole} onChange={(e) => setInvRole(e.target.value)}>
                <option value="member">Member</option>
                <option value="owner">Owner</option>
              </select>
              <button className="kbtn pri" disabled={invBusy}>
                {invBusy ? "Creating…" : "Create invite link"}
              </button>
            </form>
            {freshLink && (
              <div className="org-freshlink">
                <p>
                  Share this link with <b>{freshLink.email}</b>. It works once, only for that
                  address, and this is the only time it's shown.
                </p>
                <div className="org-mono">
                  <code>{freshLink.url}</code>
                  <button className="kbtn" onClick={() => copy(freshLink.url, "Join link")}>
                    Copy
                  </button>
                </div>
              </div>
            )}
            {(me.invites ?? []).length > 0 && (
              <>
                <h4>Pending invites</h4>
                <table className="org-table">
                  <tbody>
                    {me.invites!.map((inv) => (
                      <tr key={inv.id}>
                        <td>{inv.email}</td>
                        <td><span className="badge">{inv.role}</span></td>
                        <td className="org-row-act">
                          <button className="kbtn" onClick={() => void revoke(inv.id)}>
                            Revoke
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </>
        )}
      </div>

      {isOwner && (
        <div className="card org-card">
          <h3><Icon name="shield" size={15} /> Outbound sending</h3>
          <p className="muted">
            Messages only ever send after your approval. This controls which addresses an
            approved message may go to.
          </p>
          <label className="org-radio">
            <input
              type="radio"
              checked={mode === "allowlist"}
              onChange={() => { setMode("allowlist"); setDirty(true); }}
            />
            <span>
              <b>Allowlist</b> — only the addresses below
            </span>
          </label>
          {mode === "allowlist" && (
            <div className="org-allowlist">
              {list.map((a) => (
                <span key={a} className="org-chip">
                  {a}
                  <button
                    aria-label={`Remove ${a}`}
                    onClick={() => { setList((l) => l.filter((x) => x !== a)); setDirty(true); }}
                  >
                    ×
                  </button>
                </span>
              ))}
              <form onSubmit={addAddress} className="org-chip-add">
                <input
                  type="email"
                  placeholder="Add an address…"
                  value={newAddr}
                  onChange={(e) => setNewAddr(e.target.value)}
                />
                <button className="kbtn">Add</button>
              </form>
            </div>
          )}
          <label className="org-radio">
            <input
              type="radio"
              checked={mode === "open"}
              onChange={() => { setMode("open"); setDirty(true); }}
            />
            <span>
              <b>Open</b> — any address (each send still needs your approval)
            </span>
          </label>
          {me.global_allowlist_active && (
            <p className="muted org-note">
              This deployment also has a global allowlist; addresses outside it are refused
              regardless of the setting here.
            </p>
          )}
          {!me.settings_configured && (
            <p className="muted org-note">
              Sending is locked until you save settings here for the first time.
            </p>
          )}
          <div className="org-save">
            <button className="kbtn pri" disabled={!dirty || saveBusy} onClick={() => void saveSettings()}>
              {saveBusy ? "Saving…" : "Save sending settings"}
            </button>
          </div>
        </div>
      )}

      <div className="card org-card">
        <h3><Icon name="user" size={15} /> Your account</h3>
        <form className="org-acct" onSubmit={saveDisplayName}>
          <label htmlFor="org-name">Display name</label>
          <p className="muted">Used to sign the messages Terra drafts for you.</p>
          <div className="org-acct-row">
            <input
              id="org-name"
              type="text"
              maxLength={80}
              placeholder="e.g. Jordan Rivera"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
            <button className="kbtn" disabled={acctBusy}>Save</button>
          </div>
        </form>
        <form className="org-acct" onSubmit={changeEmail}>
          <label htmlFor="org-email">Email</label>
          <p className="muted">
            Currently {myEmail || "…"}. A confirmation link goes to the new address; the
            change applies once you confirm it.
          </p>
          <div className="org-acct-row">
            <input
              id="org-email"
              type="email"
              placeholder="new-address@company.com"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />
            <button className="kbtn" disabled={acctBusy || !newEmail.trim()}>
              Change email
            </button>
          </div>
        </form>
        <p className="muted org-note">
          Lost your authenticator? A workspace owner can reset it from the members list;
          your next sign-in sets up a new one.
        </p>
      </div>
    </div>
  );
}
