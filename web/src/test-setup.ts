import "@testing-library/jest-dom/vitest";

// findBy*/waitFor wait up to 5 s: under a full parallel run the default 1 s is too tight
// (seen as flaky failures that pass alone).
import { configure } from "@testing-library/react";
configure({ asyncUtilTimeout: 5000 });
