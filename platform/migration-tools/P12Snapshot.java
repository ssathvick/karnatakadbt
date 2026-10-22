/* Offline migration utility. The replacement services never load this class. */
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.*;

public final class P12Snapshot {
  private static String quoted(String value) {
    StringBuilder out = new StringBuilder("\"");
    for (char ch : value.toCharArray()) {
      if (ch == '\\' || ch == '"') out.append('\\').append(ch);
      else if (ch < 32) out.append(String.format("\\u%04x", (int)ch));
      else out.append(ch);
    }
    return out.append('"').toString();
  }
  private static String encoded(byte[] value) { return Base64.getEncoder().encodeToString(value); }
  public static void main(String[] args) throws Exception {
    if (args.length != 4) throw new IllegalArgumentException("Four protected file paths required");
    KeyStore store = KeyStore.getInstance("PKCS12");
    char[] password = Files.readString(Path.of(args[1]), StandardCharsets.UTF_8).toCharArray();
    try (java.io.InputStream input = Files.newInputStream(Path.of(args[0]))) { store.load(input, password); }
    StringBuilder json = new StringBuilder("{");
    boolean first = true;
    for (String alias : Collections.list(store.aliases())) {
      if (!first) json.append(','); first = false;
      json.append(quoted(alias)).append(":{");
      Key key = store.isKeyEntry(alias) ? store.getKey(alias, password) : null;
      json.append("\"format\":").append(key == null ? "null" : quoted(key.getFormat()));
      json.append(",\"algorithm\":").append(key == null ? "null" : quoted(key.getAlgorithm()));
      if (key != null) {
        byte[] bytes = key.getEncoded();
        if (bytes == null) throw new IllegalStateException("An entry is not exportable; rotation required");
        json.append(",\"encoded\":").append(quoted(encoded(bytes)));
        Arrays.fill(bytes, (byte)0);
      }
      java.security.cert.Certificate[] chain = store.getCertificateChain(alias);
      if (chain == null && store.getCertificate(alias) != null) chain = new java.security.cert.Certificate[]{store.getCertificate(alias)};
      json.append(",\"chain\":[");
      if (chain != null) for (int i=0; i<chain.length; i++) {
        if (i>0) json.append(','); json.append(quoted(encoded(chain[i].getEncoded())));
      }
      json.append("]}");
    }
    json.append('}'); Arrays.fill(password, '\0');
    byte[] wrapping = Files.readAllBytes(Path.of(args[2]));
    if (wrapping.length != 32) throw new IllegalArgumentException("AES-256 wrapping key required");
    byte[] iv = new byte[12]; new SecureRandom().nextBytes(iv);
    Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
    cipher.init(Cipher.ENCRYPT_MODE, new SecretKeySpec(wrapping, "AES"), new GCMParameterSpec(128, iv));
    cipher.updateAAD("native-certify-key-import-v1".getBytes(StandardCharsets.UTF_8));
    byte[] ciphertext = cipher.doFinal(json.toString().getBytes(StandardCharsets.UTF_8));
    byte[] output = new byte[iv.length + ciphertext.length];
    System.arraycopy(iv,0,output,0,iv.length); System.arraycopy(ciphertext,0,output,iv.length,ciphertext.length);
    Files.write(Path.of(args[3]), output);
    Arrays.fill(wrapping,(byte)0);
  }
}
