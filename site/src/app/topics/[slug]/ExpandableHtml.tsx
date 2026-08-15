"use client";

import { useState } from "react";

export default function ExpandableHtml({ html }: { html: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`expandable-html ${expanded ? "expanded" : ""}`}>
      <div
        className="md-content"
        dangerouslySetInnerHTML={{ __html: html }}
      />
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="expand-button"
        >
          過去の経過を見る ↓
        </button>
      )}
    </div>
  );
}
