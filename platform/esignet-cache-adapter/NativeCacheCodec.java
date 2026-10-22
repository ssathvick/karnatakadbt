package io.mosip.esignet.nativecache;

import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.*;
import javax.crypto.Cipher;
import javax.crypto.spec.*;

/** Transitional adapter: authenticated native writes, retained legacy readers. */
public final class NativeCacheCodec {
  private static final String PREFIX="KDBTCACHE1.";
  private static final byte[] AAD="OIDC_SERVICE/TRANSACTION_CACHE/native-v1".getBytes(StandardCharsets.UTF_8);
  private static final ThreadLocal<Boolean> PROBE=new ThreadLocal<>();
  private static final SecureRandom RANDOM=new SecureRandom();
  private static byte[] key;
  private static Path directory() { return Paths.get(System.getProperty("kdbt.cache.directory","/run/kdbt-native-cache")); }
  private static synchronized byte[] key() throws Exception {
    if(key==null) {
      byte[] master=Files.readAllBytes(directory().resolve("master-key.bin"));
      byte[] wrapped=Files.readAllBytes(directory().resolve("wrapped-key.bin"));
      if(master.length!=32 || wrapped.length!=60) throw new SecurityException("Invalid cache key configuration");
      Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
      cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(master,"AES"),new GCMParameterSpec(128,Arrays.copyOfRange(wrapped,0,12)));
      cipher.updateAAD("native-esignet-cache-key-v1".getBytes(StandardCharsets.UTF_8));
      key=cipher.doFinal(Arrays.copyOfRange(wrapped,12,wrapped.length));
      Arrays.fill(master,(byte)0);
      if(key.length!=32)throw new SecurityException("Invalid cache key length");
    }
    return key;
  }
  public static boolean nativeWrites() {
    if(PROBE.get()!=null)return PROBE.get();
    try {
      String mode=Files.readString(directory().resolve("write-mode")).trim();
      if(mode.equals("NATIVE"))return true;
      if(mode.equals("LEGACY"))return false;
      throw new SecurityException("Invalid cache write mode");
    } catch(java.io.IOException ex){throw new IllegalStateException("Cache write mode unavailable");}
  }
  public static boolean isNative(String value){return value!=null && value.startsWith(PREFIX);}
  public static String encrypt(String value) {
    try {
      byte[] nonce=new byte[12];RANDOM.nextBytes(nonce);
      Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
      cipher.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(key(),"AES"),new GCMParameterSpec(128,nonce));cipher.updateAAD(AAD);
      byte[] encrypted=cipher.doFinal(value.getBytes(StandardCharsets.UTF_8));
      byte[] result=new byte[nonce.length+encrypted.length];System.arraycopy(nonce,0,result,0,12);System.arraycopy(encrypted,0,result,12,encrypted.length);
      return PREFIX+Base64.getUrlEncoder().withoutPadding().encodeToString(result);
    } catch(Exception ex){throw new IllegalStateException("Native cache encryption failed");}
  }
  public static String decrypt(String value) {
    try {
      if(!isNative(value))throw new SecurityException();
      byte[] raw=Base64.getUrlDecoder().decode(value.substring(PREFIX.length()));if(raw.length<28)throw new SecurityException();
      Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,new SecretKeySpec(key(),"AES"),new GCMParameterSpec(128,Arrays.copyOfRange(raw,0,12)));cipher.updateAAD(AAD);
      return new String(cipher.doFinal(Arrays.copyOfRange(raw,12,raw.length)),StandardCharsets.UTF_8);
    } catch(Exception ex){throw new IllegalStateException("Native cache authentication failed");}
  }
  public static void probeMode(Boolean value){if(value==null)PROBE.remove();else PROBE.set(value);}
}
