import { createApp } from "vue";
import App from "./App.vue";
import {
  fluentButton,
  fluentCard,
  fluentCheckbox,
  fluentDesignSystemProvider,
  fluentDivider,
  fluentOption,
  fluentProgress,
  fluentRadio,
  fluentRadioGroup,
  fluentSelect,
  fluentTextArea,
  fluentTextField,
  provideFluentDesignSystem,
} from "@fluentui/web-components";

provideFluentDesignSystem().register(
  fluentButton(),
  fluentCard(),
  fluentCheckbox(),
  fluentDesignSystemProvider(),
  fluentDivider(),
  fluentOption(),
  fluentProgress(),
  fluentRadio(),
  fluentRadioGroup(),
  fluentSelect(),
  fluentTextArea(),
  fluentTextField(),
);

// https://github.com/microsoft/fluentui/issues/30886
// const syncSystemTheme = (event?: MediaQueryListEvent) => {
//   const isDark = event?.matches ?? window.matchMedia("(prefers-color-scheme: dark)").matches;
//   document.documentElement.dataset.theme = isDark ? "dark" : "light";
// };

// const themeQuery = window.matchMedia("(prefers-color-scheme: dark)");
// try {
//   syncSystemTheme();
//   if ("addEventListener" in themeQuery) {
//     themeQuery.addEventListener("change", syncSystemTheme);
//   } else {
//     (themeQuery as MediaQueryList & { addListener: (listener: (event: MediaQueryListEvent) => void) => void }).addListener(
//       syncSystemTheme,
//     );
//   }
// } catch (error) {
//   console.error("Failed to initialize Fluent theme.", error);
// }

createApp(App).mount("#app");
