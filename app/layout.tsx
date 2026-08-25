import type { Metadata } from "next";
import "./globals.css";

const title = "事件选股 · 财经事件智能解读工具";
const description = "面向普通投资者的财经事件解读工具，快速看懂新闻、影响逻辑与后续验证点。";

export const metadata: Metadata = {
  metadataBase: new URL("https://dequanma1.github.io"),
  title,
  description,
  openGraph: {
    title,
    description,
    type: "website",
    images: [{ url: "/og.png", width: 1728, height: 904, alt: "事件选股：财经事件智能解读工具" }],
  },
  twitter: {
    card: "summary_large_image",
    title,
    description,
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
