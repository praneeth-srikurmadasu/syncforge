import { describeUserAgent } from './recent-sign-ins.component';

describe('describeUserAgent', () => {
  it('names common browsers and systems', () => {
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0 Safari/537.36',
      ),
    ).toBe('Chrome on Windows');
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/158.0 Safari/537.36 Edg/158.0',
      ),
    ).toBe('Edge on Windows');
    expect(
      describeUserAgent(
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_1) Gecko/20100101 Firefox/140.0',
      ),
    ).toBe('Firefox on macOS');
    expect(
      describeUserAgent(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 Version/19.0 Mobile Safari/604.1',
      ),
    ).toBe('Safari on iOS');
  });

  it('falls back to the raw value or Unknown', () => {
    expect(describeUserAgent(null)).toBe('Unknown');
    expect(describeUserAgent('python-httpx/0.28')).toBe('python-httpx/0.28');
  });
});
