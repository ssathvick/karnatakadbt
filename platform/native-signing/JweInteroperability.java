import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.security.cert.*;
import java.util.*;
import org.jose4j.jwe.JsonWebEncryption;

/** Independent JOSE oracle. Inputs are exclusively disposable synthetic keys. */
public class JweInteroperability {
 public static void main(String[] args)throws Exception {
  Path p=Paths.get(args[0]);
  PrivateKey key=KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(Files.readAllBytes(p.resolve("synthetic-private.der"))));
  X509Certificate cert=(X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(Files.newInputStream(p.resolve("synthetic-certificate.der")));
  String plain=Files.readString(p.resolve("synthetic-payload.json"));
  JsonWebEncryption nativeValue=new JsonWebEncryption();
  nativeValue.setCompactSerialization(Files.readString(p.resolve("native.jwe")));
  nativeValue.setKey(key);
  if(!plain.equals(nativeValue.getPlaintextString()))throw new IllegalStateException("Native JWE interoperability failed");
  for(boolean compressed:new boolean[]{true,false}){
   JsonWebEncryption jwe=new JsonWebEncryption();
   jwe.setAlgorithmHeaderValue("RSA-OAEP-256");jwe.setEncryptionMethodHeaderParameter("A256GCM");
   jwe.setHeader("cty","JWT");jwe.setHeader("typ","JWT");
   jwe.setKeyIdHeaderValue(Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(cert.getEncoded())));
   jwe.setKey(cert.getPublicKey());jwe.setPayload(plain);
   if(compressed)jwe.enableDefaultCompression();
   Files.writeString(p.resolve(compressed?"java-compressed.jwe":"java-uncompressed.jwe"),jwe.getCompactSerialization());
  }
  System.out.println("{\"native_jwe_decrypted_by_independent_java_jose\":true,\"java_compressed_and_uncompressed_jwe_created\":true}");
 }
}
