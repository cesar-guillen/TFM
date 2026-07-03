export default function ChatPanel() {
  return (
    <>
      <div className="panel-header">
        <h2>Chat</h2>
      </div>
      <div className="panel-body">
        <div className="empty-state">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none">
            <path
              d="M4 4h16v11H8l-4 4V4Z"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinejoin="round"
            />
          </svg>
          <h3>Chat coming soon</h3>
          <p>Ask questions or request edits to the matrix once retrieval is wired up.</p>
        </div>
      </div>
      <div
        style={{
          display: "flex",
          gap: "0.5rem",
          padding: "0.85rem",
          borderTop: "1px solid var(--border-soft)",
        }}
      >
        <input
          type="text"
          placeholder="Coming soon..."
          disabled
          className="text-input"
          style={{ flex: 1 }}
        />
        <button className="btn btn-primary" disabled>
          Send
        </button>
      </div>
    </>
  );
}
