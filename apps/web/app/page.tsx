import type { Metadata } from "next";
import Workspace from "./workspace";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default function Home() {
  return <Workspace />;
}
