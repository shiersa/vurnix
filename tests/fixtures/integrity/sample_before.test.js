test('adds numbers', () => {
  expect(1 + 1).toBe(2);
  expect([1, 2, 3]).toContain(2);
});

it('concatenates strings', () => {
  expect('a' + 'b').toBe('ab');
});
