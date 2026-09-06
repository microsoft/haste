# Impact: Versioned Prediction Editing

## Risks

| Risk | Mitigation |
|---|---|
| Saved version labels differ from its download | Reload/select the returned version after save |
| Edits overwrite raw or earlier saved output | Separate version artifacts and conflict protection |
| Two swipe panes show different classes | Mirror feature state and clear it before source replacement |
| Assessment ignores human overrides | Override-aware class/score helpers and report fixtures |
| Wrong workflow gets threshold sliders | Use producer/model schema, never score-value heuristics |
| Large edit state blocks interaction | Reuse #136's columnar sidecar and feature-state design |
| Reusing #136 revives unwanted queues | No prep workflow/config/API; explicit absence coverage |

## Boundaries

Versioned editing depends on the shared eager-results stage and the layer
geometry contract from #183. It does not require retraining a model or changing
storage backends. Publishing saved edits is a separate feature.
