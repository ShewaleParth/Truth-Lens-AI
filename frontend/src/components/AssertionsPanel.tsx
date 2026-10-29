import React from 'react';
import { ListChecks, Tag, Box } from 'lucide-react';
import type { Assertion } from '../types';

interface AssertionsPanelProps {
  claims: Assertion[];
}

export const AssertionsPanel: React.FC<AssertionsPanelProps> = ({ claims }) => {
  return (
    <div className="card assertions-panel">
      <div className="panel-header-row">
        <div className="panel-title-group">
          <ListChecks size={20} className="panel-icon" />
          <h3 className="panel-title">Extracted Assertions</h3>
        </div>
        <span className="count-badge">{claims.length} decomposed statement{claims.length === 1 ? '' : 's'}</span>
      </div>

      <p className="panel-subtitle">
        The input message was decomposed into individual testable factual assertions for targeted evidence retrieval.
      </p>

      {claims.length === 0 ? (
        <div className="empty-state-notice">
          <p>No distinct factual assertions could be parsed from the input text.</p>
        </div>
      ) : (
        <div className="assertions-list">
          {claims.map((claim, idx) => (
            <div key={idx} className="assertion-card">
              <div className="assertion-index-badge">{idx + 1}</div>
              <div className="assertion-content">
                <p className="assertion-text">"{claim.text}"</p>

                <div className="assertion-metadata-row">
                  <div className="assertion-type-tag">
                    <Tag size={12} />
                    <span>Type: <strong>{claim.assertion_type}</strong></span>
                  </div>

                  {claim.entities && claim.entities.length > 0 && (
                    <div className="entities-group">
                      <Box size={12} className="entities-icon" />
                      <span className="entities-label">Entities:</span>
                      <div className="entity-tags">
                        {claim.entities.map((entity, eIdx) => (
                          <span key={eIdx} className="entity-chip">
                            {entity}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
