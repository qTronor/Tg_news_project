import { getStoredTokens, storeTokens, clearTokens } from "@/lib/auth";

const mockLocalStorage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(window, "localStorage", { value: mockLocalStorage });

describe("token management", () => {
  beforeEach(() => {
    mockLocalStorage.clear();
  });

  it("returns null tokens when nothing stored", () => {
    const { access, refresh } = getStoredTokens();
    expect(access).toBeNull();
    expect(refresh).toBeNull();
  });

  it("stores and retrieves tokens", () => {
    storeTokens({
      access_token: "acc123",
      refresh_token: "ref456",
      expires_in: 1800,
    });

    const { access, refresh } = getStoredTokens();
    expect(access).toBe("acc123");
    expect(refresh).toBe("ref456");
  });

  it("clears all tokens", () => {
    storeTokens({
      access_token: "acc",
      refresh_token: "ref",
      expires_in: 1800,
    });
    clearTokens();

    const { access, refresh } = getStoredTokens();
    expect(access).toBeNull();
    expect(refresh).toBeNull();
  });
});
