import java.nio.file.*;
import java.security.*;
import java.security.spec.*;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.util.*;
import javax.crypto.*;
import javax.crypto.spec.*;
import com.fasterxml.jackson.databind.ObjectMapper;

/** Build an isolated PKCS12 recovery projection from authenticated ciphertext. */
public class BuildSoftwareKeyStore {
 public static void main(String[] args)throws Exception{
  ObjectMapper mapper=new ObjectMapper();Map<String,String> cfg=mapper.readValue(Files.readAllBytes(Paths.get(args[0])),Map.class);
  byte[] wrapping=Base64.getDecoder().decode(cfg.get("wrapping_key"));char[] password=cfg.get("password").toCharArray();
  try{
   byte[] input=Files.readAllBytes(Paths.get(args[1]));Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
   cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(wrapping,"AES"),new GCMParameterSpec(128,Arrays.copyOfRange(input,0,12)));
   cipher.updateAAD("native-keymanager-reverse-export-v1".getBytes(java.nio.charset.StandardCharsets.UTF_8));
   byte[] plain=cipher.doFinal(Arrays.copyOfRange(input,12,input.length));
   Map<String,Map<String,Object>> entries=mapper.readValue(plain,Map.class);Arrays.fill(plain,(byte)0);
   KeyStore store=KeyStore.getInstance("PKCS12");store.load(null,password);int privateCount=0,secretCount=0,publicCount=0;
   for(Map.Entry<String,Map<String,Object>> item:entries.entrySet()){
    String alias=item.getKey();Map<String,Object> entry=item.getValue();
    List<String> chain=(List<String>)entry.get("chain");List<Certificate> certificates=new ArrayList<>();
    if(chain!=null)for(String value:chain)certificates.add(CertificateFactory.getInstance("X.509").generateCertificate(new java.io.ByteArrayInputStream(Base64.getDecoder().decode(value))));
    if("PKCS#8".equals(entry.get("format"))){
     byte[] encoded=Base64.getDecoder().decode((String)entry.get("encoded"));
     PrivateKey key=KeyFactory.getInstance((String)entry.get("algorithm")).generatePrivate(new PKCS8EncodedKeySpec(encoded));Arrays.fill(encoded,(byte)0);
     store.setKeyEntry(alias,key,password,certificates.toArray(new Certificate[0]));privateCount++;
    }else if("RAW".equals(entry.get("format"))){
     byte[] encoded=Base64.getDecoder().decode((String)entry.get("encoded"));
     store.setEntry(alias,new KeyStore.SecretKeyEntry(new SecretKeySpec(encoded,(String)entry.get("algorithm"))),new KeyStore.PasswordProtection(password));Arrays.fill(encoded,(byte)0);secretCount++;
    }else{store.setCertificateEntry(alias,certificates.get(0));publicCount++;}
   }
   try(java.io.OutputStream output=Files.newOutputStream(Paths.get(args[2]))){store.store(output,password);}
   System.out.println("{\"private_keys\":"+privateCount+",\"secret_keys\":"+secretCount+",\"public_certificates\":"+publicCount+",\"recovery_store_built\":true}");
  }finally{Arrays.fill(wrapping,(byte)0);Arrays.fill(password,'\0');}
 }
}
