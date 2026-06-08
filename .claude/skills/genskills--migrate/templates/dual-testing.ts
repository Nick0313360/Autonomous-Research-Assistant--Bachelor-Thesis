describe.each([
  ['legacy', legacyImplementation],
  ['new', newImplementation],
])('%s implementation', (name, impl) => {
  it('should calculate total correctly', () => {
    expect(impl.calculateTotal([10, 20, 30])).toBe(60);
  });

  it('should handle empty input', () => {
    expect(impl.calculateTotal([])).toBe(0);
  });
});
