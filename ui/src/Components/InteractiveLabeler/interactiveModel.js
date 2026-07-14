// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// In-browser damage-prediction model, ported from
// ~/interactive-building-labeler/index.html. The interactive labeler trains a
// lightweight classifier on the per-building MOSAIKS features (f_0..f_N) that
// were baked into the embeddings GeoJSON, then predicts damage for every
// building — all client-side, no server round-trip per label.
//
// v1 ships Logistic Regression (index.html's default model): a small
// hand-rolled gradient-descent implementation with no dependencies — binary
// (LogisticRegression) or multiclass via one-vs-rest (OvRLogisticRegression).
// A Random Forest option (e.g. via `ml-random-forest`) is a future follow-up;
// adding the npm dep here requires regenerating ui/package-lock.json.
//
// Class encoding (matches index.html): Intact = 0, Damaged = 1, Cloudy = 2.

import { getGpu, gpuBackendName, gpuOvrPredict } from "./gpuLogreg.js";

export const CLASS_INTACT = 0;
export const CLASS_DAMAGED = 1;
export const CLASS_CLOUDY = 2;

// ── Binary logistic regression with standardization + L2 ────────────────────
export class LogisticRegression {
  constructor({ learningRate = 0.1, numSteps = 500, lambda = 0.01 } = {}) {
    this.lr = learningRate;
    this.steps = numSteps;
    this.lambda = lambda;
    this.w = null;
    this.b = 0;
    this.mean = null;
    this.std = null;
  }

  _sigmoid(z) {
    return 1 / (1 + Math.exp(-z));
  }

  _standardize(X) {
    return X.map((row) =>
      row.map((v, j) => (v - this.mean[j]) / (this.std[j] || 1))
    );
  }

  train(X, Y) {
    const n = X.length;
    const d = X[0].length;
    this.mean = new Array(d).fill(0);
    this.std = new Array(d).fill(0);
    for (let i = 0; i < n; i++)
      for (let j = 0; j < d; j++) this.mean[j] += X[i][j];
    for (let j = 0; j < d; j++) this.mean[j] /= n;
    for (let i = 0; i < n; i++)
      for (let j = 0; j < d; j++)
        this.std[j] += (X[i][j] - this.mean[j]) ** 2;
    for (let j = 0; j < d; j++) this.std[j] = Math.sqrt(this.std[j] / n);

    const Xs = this._standardize(X);
    this.w = new Array(d).fill(0);
    this.b = 0;

    for (let step = 0; step < this.steps; step++) {
      const dw = new Array(d).fill(0);
      let db = 0;
      for (let i = 0; i < n; i++) {
        let z = this.b;
        for (let j = 0; j < d; j++) z += this.w[j] * Xs[i][j];
        const p = this._sigmoid(z);
        const err = p - Y[i];
        for (let j = 0; j < d; j++) dw[j] += err * Xs[i][j];
        db += err;
      }
      for (let j = 0; j < d; j++)
        this.w[j] -= this.lr * (dw[j] / n + this.lambda * this.w[j]);
      this.b -= this.lr * (db / n);
    }
  }

  predictProba(X) {
    const Xs = this._standardize(X);
    return Xs.map((row) => {
      let z = this.b;
      for (let j = 0; j < row.length; j++) z += this.w[j] * row[j];
      return this._sigmoid(z);
    });
  }

  predict(X) {
    return this.predictProba(X).map((p) => (p >= 0.5 ? 1 : 0));
  }
}

// ── One-vs-Rest wrapper for multiclass logistic regression ──────────────────
export class OvRLogisticRegression {
  constructor(opts) {
    this.opts = opts;
    this.classifiers = {};
    this.classes = [];
  }

  train(X, Y) {
    this.classes = [...new Set(Y)].sort((a, b) => a - b);
    this.classifiers = {};
    for (const c of this.classes) {
      const binaryY = Y.map((y) => (y === c ? 1 : 0));
      const lr = new LogisticRegression(this.opts);
      lr.train(X, binaryY);
      this.classifiers[c] = lr;
    }
  }

  predictProba(X) {
    const rawProbs = {};
    for (const c of this.classes) {
      rawProbs[c] = this.classifiers[c].predictProba(X);
    }
    return X.map((_, i) => {
      let sum = 0;
      const p = {};
      for (const c of this.classes) {
        p[c] = rawProbs[c][i];
        sum += p[c];
      }
      for (const c of this.classes) p[c] /= sum;
      return p;
    });
  }

  predict(X) {
    const probs = this.predictProba(X);
    return probs.map((p) => {
      let best = this.classes[0];
      let bestP = -1;
      for (const c of this.classes) {
        if (p[c] > bestP) {
          bestP = p[c];
          best = c;
        }
      }
      return best;
    });
  }
}

// ── Model factory ───────────────────────────────────────────────────────────
// Returns a trained logistic-regression model exposing predict(matrix):
// binary LogisticRegression for 2 classes, one-vs-rest for 3+.
export function buildModel(entries) {
  const X = entries.map((d) => d.features);
  const Y = entries.map((d) => d.label);
  const nClasses = new Set(Y).size;
  const opts = { learningRate: 0.1, numSteps: 500, lambda: 0.01 };

  if (nClasses <= 2) {
    const lr = new LogisticRegression(opts);
    lr.train(X, Y);
    return lr;
  }
  const ovr = new OvRLogisticRegression(opts);
  ovr.train(X, Y);
  return ovr;
}

// ── Unified async predict (WebGPU, CPU fallback) ────────────────────────────
// Trains one-vs-rest logistic regression on `entries` and returns the predicted
// class for each row of `queryMatrix`. Uses WebGPU when available; otherwise the
// CPU implementation above. Returns { predictions, backend }.
export async function predictClasses(
  entries,
  queryMatrix,
  opts = { learningRate: 0.1, numSteps: 500, lambda: 0.01 }
) {
  if (queryMatrix.length === 0) {
    return { predictions: [], backend: gpuBackendName() };
  }
  const classes = [...new Set(entries.map((e) => e.label))].sort(
    (a, b) => a - b
  );

  const gpu = await getGpu();
  if (gpu) {
    try {
      const predictions = await gpuOvrPredict(
        gpu,
        entries,
        classes,
        queryMatrix,
        opts
      );
      return { predictions, backend: "WebGPU" };
    } catch (e) {
      console.warn("WebGPU predict failed; falling back to CPU.", e);
    }
  }

  // CPU fallback — always one-vs-rest (robust to any label set).
  const ovr = new OvRLogisticRegression(opts);
  ovr.train(
    entries.map((e) => e.features),
    entries.map((e) => e.label)
  );
  return { predictions: ovr.predict(queryMatrix), backend: "CPU" };
}

// ── Feature extraction ──────────────────────────────────────────────────────
// Detect the f_0..f_N columns once (sorted numerically) and pull them off a
// feature's properties as a plain number array.
export function detectFeatureKeys(props) {
  return Object.keys(props)
    .filter((k) => /^f_\d+$/.test(k))
    .sort((a, b) => parseInt(a.slice(2), 10) - parseInt(b.slice(2), 10));
}

export function extractFeatureVector(props, featureKeys) {
  return featureKeys.map((k) => props[k]);
}

// A feature row is usable for training/inference only if every value is a
// finite number (embedding placeholders for off-raster buildings are NaN).
export function isValidVector(vec) {
  return vec && vec.every((v) => v != null && !Number.isNaN(v));
}

// ── Train/test stratified split (for the validation metrics panel) ──────────
export function stratifiedSplit(entries, testFrac = 0.25) {
  const byClass = {};
  entries.forEach((e) => (byClass[e.label] = byClass[e.label] || []).push(e));
  const train = [];
  const test = [];
  Object.values(byClass).forEach((cls) => {
    const shuffled = [...cls].sort(() => Math.random() - 0.5);
    const nTest = Math.max(1, Math.round(shuffled.length * testFrac));
    test.push(...shuffled.slice(0, nTest));
    train.push(...shuffled.slice(nTest));
  });
  return { train, test };
}

// Single-split holdout estimate of precision / recall / F1 for the Damaged
// class (class 1 = positive, everything else = negative). Trains one OvR
// model on the stratified majority split, evaluates on the held-out
// minority split. Cheaper than k-fold (one OvR training instead of k) so
// it can run on every label click without blocking the prediction
// pipeline. Returns null when the data is too thin to form a meaningful
// split (e.g. only one class, or fewer than 2 of either class).
//
// Note: metrics will fluctuate click-to-click because the split is
// re-randomized. That's the cost of getting fresh metrics on every
// retrain without paying for full CV. The dominant trend across a
// labeling session remains informative.
export async function holdoutMetricsDamaged(
  entries,
  testFrac = 0.2,
  damagedClass = 1
) {
  const usable = entries.filter((e) => isValidVector(e.features));
  const pos = usable.filter((e) => e.label === damagedClass);
  const neg = usable.filter((e) => e.label !== damagedClass);
  if (pos.length < 2 || neg.length < 2 || usable.length < 4) return null;

  const { train, test } = stratifiedSplit(usable, testFrac);
  // The stratified split guarantees at least 1 test sample per class;
  // we also need at least one positive AND one negative in train so the
  // OvR pass has both classes.
  const trainClasses = new Set(train.map((e) => e.label));
  if (trainClasses.size < 2 || test.length === 0) return null;

  const { predictions: preds } = await predictClasses(
    train,
    test.map((d) => d.features)
  );

  let tp = 0;
  let fp = 0;
  let fn = 0;
  test.forEach((e, idx) => {
    const predDamaged = preds[idx] === damagedClass;
    const isDamaged = e.label === damagedClass;
    if (predDamaged && isDamaged) tp++;
    else if (predDamaged && !isDamaged) fp++;
    else if (!predDamaged && isDamaged) fn++;
  });

  const precision = tp / (tp + fp) || 0;
  const recall = tp / (tp + fn) || 0;
  const f1 = (2 * precision * recall) / (precision + recall) || 0;
  return {
    precision,
    recall,
    f1,
    nTrain: train.length,
    nTest: test.length,
    nPos: pos.length,
    nNeg: neg.length,
  };
}

export function computeClassMetrics(preds, labels) {
  const classes = [...new Set([...preds, ...labels])].sort((a, b) => a - b);
  const perClass = {};
  for (const c of classes) {
    const tp = preds.filter((p, i) => p === c && labels[i] === c).length;
    const fp = preds.filter((p, i) => p === c && labels[i] !== c).length;
    const fn = preds.filter((p, i) => p !== c && labels[i] === c).length;
    const prec = tp / (tp + fp) || 0;
    const rec = tp / (tp + fn) || 0;
    const f1 = (2 * prec * rec) / (prec + rec) || 0;
    perClass[c] = { prec, rec, f1 };
  }
  const acc =
    preds.filter((p, i) => p === labels[i]).length / (preds.length || 1);
  return { perClass, acc };
}

// ── Rank-based binary AUC (Mann–Whitney U statistic) ────────────────────────
// AUC = probability that a random positive scores above a random negative.
// Computed from ranks with average ranks for ties:
//   AUC = (sum_of_ranks_of_positives - nPos*(nPos+1)/2) / (nPos*nNeg)
// Returns null for degenerate inputs (empty, or no positives / no negatives)
// since AUC is undefined without at least one of each class.
export function binaryAUC(scores, labels01) {
  const n = scores.length;
  if (n === 0) return null;
  let nPos = 0;
  let nNeg = 0;
  for (let i = 0; i < n; i++) {
    if (labels01[i] === 1) nPos++;
    else nNeg++;
  }
  if (nPos === 0 || nNeg === 0) return null;

  // Rank scores ascending (1-based), assigning the average rank to ties.
  const order = scores.map((_, i) => i).sort((a, b) => scores[a] - scores[b]);
  const ranks = new Array(n);
  let i = 0;
  while (i < n) {
    let j = i;
    while (j + 1 < n && scores[order[j + 1]] === scores[order[i]]) j++;
    const avgRank = (i + j) / 2 + 1; // midpoint of positions i..j, 1-based
    for (let k = i; k <= j; k++) ranks[order[k]] = avgRank;
    i = j + 1;
  }

  let sumRanksPos = 0;
  for (let r = 0; r < n; r++) {
    if (labels01[r] === 1) sumRanksPos += ranks[r];
  }
  return (sumRanksPos - (nPos * (nPos + 1)) / 2) / (nPos * nNeg);
}

// Fisher–Yates in-place shuffle on a shallow copy (leaves the input intact).
function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// Mean + sample (n-1 denominator) standard deviation across `vals`.
//   n >= 2 -> { mean, std, n }
//   n == 1 -> { mean, std: 0, n }   (a single fold has no spread)
//   n == 0 -> { mean: null, std: null, n: 0 }
function meanStd(vals) {
  const n = vals.length;
  if (n === 0) return { mean: null, std: null, n: 0 };
  const mean = vals.reduce((s, v) => s + v, 0) / n;
  if (n === 1) return { mean, std: 0, n: 1 };
  const variance = vals.reduce((s, v) => s + (v - mean) ** 2, 0) / (n - 1);
  return { mean, std: Math.sqrt(variance), n };
}

// ── Stratified k-fold cross-validated per-class metrics ─────────────────────
// Runs stratified k-fold cross-validation over the labeled `entries` and
// reports per-class precision, recall, and one-vs-rest AUC, each aggregated
// across folds as mean ± sample standard deviation.
//
// Fold-stdev semantics: each fold produces (at most) one value per class per
// metric; we report the mean and the *sample* stdev (n-1 denominator) across
// the folds that yielded a defined value. This estimates the fold-to-fold
// variability of the metric — how sensitive it is to which subset is held
// out — NOT a confidence interval on any single trained model. Folds where a
// metric is undefined (precision when there are no predicted positives, recall
// when the fold has no true positives, or AUC when the held-out fold is
// single-class for that label) are skipped for that metric so one degenerate
// fold does not drag the estimate toward 0.
export function crossValidateMetrics(entries, { k = 5, opts } = {}) {
  const usable = (entries || []).filter((e) => isValidVector(e.features));
  const classes = [...new Set(usable.map((e) => e.label))].sort(
    (a, b) => a - b
  );
  if (classes.length < 2) {
    return {
      ok: false,
      reason: "Need at least 2 labeled classes to run cross-validation.",
    };
  }

  // Group members by class, count support, and find the smallest class.
  const byClass = {};
  for (const c of classes) byClass[c] = [];
  for (const e of usable) byClass[e.label].push(e);
  const support = {};
  let minClassCount = Infinity;
  for (const c of classes) {
    support[c] = byClass[c].length;
    if (support[c] < minClassCount) minClassCount = support[c];
  }

  // Effective folds cannot exceed the smallest class's member count, else a
  // fold could be missing an entire class.
  const effK = Math.min(k, minClassCount);
  if (effK < 2) {
    return {
      ok: false,
      reason: `Not enough samples per class for cross-validation (smallest class has ${minClassCount}; need at least 2).`,
    };
  }

  const modelOpts = opts || { learningRate: 0.1, numSteps: 500, lambda: 0.01 };

  // Stratified fold assignment: shuffle each class, then round-robin its
  // members across the effK folds. Because every class has >= effK members,
  // each fold receives at least one member of every class.
  const folds = Array.from({ length: effK }, () => []);
  for (const c of classes) {
    shuffle(byClass[c]).forEach((e, i) => folds[i % effK].push(e));
  }

  const precVals = {};
  const recVals = {};
  const aucVals = {};
  for (const c of classes) {
    precVals[c] = [];
    recVals[c] = [];
    aucVals[c] = [];
  }

  for (let i = 0; i < effK; i++) {
    const test = folds[i];
    const train = [];
    for (let j = 0; j < effK; j++) if (j !== i) train.push(...folds[j]);
    if (train.length === 0 || test.length === 0) continue;
    // Guard against the (rare, tiny-data) case where the training split is
    // missing a class — OvR needs both classes represented to be meaningful.
    if (new Set(train.map((e) => e.label)).size < 2) continue;

    const ovr = new OvRLogisticRegression(modelOpts);
    ovr.train(
      train.map((e) => e.features),
      train.map((e) => e.label)
    );

    const testX = test.map((e) => e.features);
    const testTrue = test.map((e) => e.label);
    const preds = ovr.predict(testX);

    for (const c of classes) {
      // Per-class precision / recall from the argmax predictions.
      let tp = 0;
      let fp = 0;
      let fn = 0;
      for (let r = 0; r < testTrue.length; r++) {
        const predC = preds[r] === c;
        const trueC = testTrue[r] === c;
        if (predC && trueC) tp++;
        else if (predC && !trueC) fp++;
        else if (!predC && trueC) fn++;
      }
      if (tp + fp > 0) precVals[c].push(tp / (tp + fp));
      if (tp + fn > 0) recVals[c].push(tp / (tp + fn));

      // Per-class one-vs-rest AUC from the raw (un-normalized) sigmoid scores.
      const clf = ovr.classifiers[c];
      if (clf) {
        const y01 = testTrue.map((t) => (t === c ? 1 : 0));
        const auc = binaryAUC(clf.predictProba(testX), y01);
        if (auc != null) aucVals[c].push(auc);
      }
    }
  }

  const perClass = {};
  for (const c of classes) {
    perClass[c] = {
      precision: meanStd(precVals[c]),
      recall: meanStd(recVals[c]),
      auc: meanStd(aucVals[c]),
      support: support[c],
    };
  }

  return {
    ok: true,
    k: effK,
    requestedK: k,
    classes,
    perClass,
    nTotal: usable.length,
  };
}
