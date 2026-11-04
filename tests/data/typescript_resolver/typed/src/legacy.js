class Cache {
  get(key) { return key; }
  put(key) { return key; }
}

class Legacy {
  /**
   * @param {Cache} cache the cache
   */
  constructor(cache) {
    this.cache = cache;
    /** @type {Cache} */
    this.other = makeCache();
    this.made = new Cache();
  }

  byConvention() { this.cache.get("a"); }
  byJsdocType() { this.other.put("b"); }
  byNew() { this.made.get("c"); }
}

/**
 * @param {?Cache} [cache] optional
 */
function use(cache) {
  cache.put("d");
}

/**
 * @template T
 * @param {T} t
 */
function useGeneric(t) {
  t.put("x");
}

/** @param {Object} cache */
function useObject(cache) {
  cache.put("x");
}

function makeCache() { return new Cache(); }

module.exports = { Legacy, use, useGeneric, useObject, makeCache };
