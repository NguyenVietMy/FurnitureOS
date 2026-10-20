// Publication needs one honestly reviewed Style shared by all required roles.
// Multiple alternatives within a category do not need identical tag sets.
export function commonAnchorStyles(entries) {
  const styles = ['sofa', 'table', 'chair'].map((category) => new Set(entries
    .filter((entry) => entry.category === category)
    .flatMap((entry) => entry.privateStyleIds)));
  return [...styles[0]].filter((id) => styles[1].has(id) && styles[2].has(id));
}
