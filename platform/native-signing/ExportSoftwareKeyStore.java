import java.nio.file.*;
import java.security.*;
import java.security.cert.Certificate;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.*;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Protected offline PKCS12 migration utility; never emits key material. */
public class ExportSoftwareKeyStore {
 public static void main(String[] args)throws Exception{
  ObjectMapper mapper=new ObjectMapper();Map<String,String> cfg=mapper.readValue(Files.readAllBytes(Paths.get(args[0])),Map.class);
  char[] password=cfg.get("password").toCharArray();byte[] wrapping=Base64.getDecoder().decode(cfg.get("wrapping_key"));
  try{
   KeyStore store=KeyStore.getInstance("PKCS12");try(java.io.InputStream input=Files.newInputStream(Paths.get(cfg.get("path")))){store.load(input,password);}
   Map<String,Object> entries=new TreeMap<>();int privateCount=0,secretCount=0;
   for(Enumeration<String> names=store.aliases();names.hasMoreElements();){
    String alias=names.nextElement();Map<String,Object> entry=new LinkedHashMap<>();
    if(store.isKeyEntry(alias)){
     Key key=store.getKey(alias,password);byte[] encoded=key.getEncoded();
     if(encoded==null)throw new IllegalStateException("Software-key entry is not exportable; controlled rotation required");
     entry.put("algorithm",key.getAlgorithm());entry.put("format",key.getFormat());entry.put("encoded",Base64.getEncoder().encodeToString(encoded));Arrays.fill(encoded,(byte)0);
     if(key instanceof PrivateKey)privateCount++;else secretCount++;
    }
    List<String> chain=new ArrayList<>();Certificate[] certificates=store.getCertificateChain(alias);
    if(certificates!=null)for(Certificate cert:certificates)chain.add(Base64.getEncoder().encodeToString(cert.getEncoded()));
    else if(store.getCertificate(alias)!=null)chain.add(Base64.getEncoder().encodeToString(store.getCertificate(alias).getEncoded()));
    entry.put("chain",chain);entries.put(alias,entry);
   }
   byte[] nonce=new byte[12];new SecureRandom().nextBytes(nonce);Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
   cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(wrapping,"AES"),new GCMParameterSpec(128,nonce));
   cipher.updateAAD("native-keymanager-source-export-v1".getBytes(java.nio.charset.StandardCharsets.UTF_8));
   byte[] plain=mapper.writeValueAsBytes(entries);byte[] encrypted=cipher.doFinal(plain);Arrays.fill(plain,(byte)0);
   byte[] output=new byte[nonce.length+encrypted.length];System.arraycopy(nonce,0,output,0,nonce.length);System.arraycopy(encrypted,0,output,nonce.length,encrypted.length);
   Files.write(Paths.get(args[1]),output);
   System.out.println("{\"private_keys\":"+privateCount+",\"secret_keys\":"+secretCount+",\"encrypted_archive_created\":true}");
  }finally{Arrays.fill(password,'\0');Arrays.fill(wrapping,(byte)0);}
 }
}
